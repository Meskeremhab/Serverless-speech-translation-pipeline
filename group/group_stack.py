from aws_cdk import (
    aws_s3 as s3,
    Stack,
    Duration,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

class GroupStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # S3 bucket for audio files and translations
        bucket = s3.Bucket(self, "TranslationBucket")
        
        # Create IAM role for Step Functions
        sfn_role = iam.Role(
            self,
            "StepFunctionsRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )

        # Grant necessary permissions to the IAM role
        bucket.grant_read_write(sfn_role)
        policies = [
            "AmazonTranscribeFullAccess",
            "TranslateFullAccess",
            "AmazonPollyFullAccess",
            "AmazonS3ReadOnlyAccess"
        ]
        for policy in policies:
            sfn_role.add_managed_policy(
                iam.ManagedPolicy.from_aws_managed_policy_name(policy)
            )

        # Step Functions Tasks
        start_transcribe_task = tasks.CallAwsService(self, "StartTranscription",
            service="transcribe",
            action="startTranscriptionJob",
            parameters={
                "TranscriptionJobName.$": "States.Format('TranscriptionJob-{}', $$.Execution.Name)",
                "IdentifyLanguage": True,  
                "MediaFormat": "mp3",
                "Media": {
                    "MediaFileUri.$": "States.Format('s3://{}/{}', $.requestParameters.bucketName,  $.requestParameters.key)"
                },
                "OutputBucketName.$": "$.requestParameters.bucketName"
            },
            iam_resources=["*"],
            result_path="$.TranscriptionJobDetails",
        )

        wait_state = sfn.Wait(self, "WaitForTranscription",
            time=sfn.WaitTime.duration(Duration.minutes(1))
        )

        get_transcription_task = tasks.CallAwsService(self, "GetTranscription",
            service="transcribe",
            action="getTranscriptionJob",
            parameters={
                "TranscriptionJobName.$": "$.TranscriptionJobDetails.TranscriptionJob.TranscriptionJobName"
            },
            iam_resources=["*"],
            result_path="$.TranscriptionJobDetails",
        )

        check_transcription_status = sfn.Choice(self, "IsTranscriptionComplete")
        transcription_complete = sfn.Condition.string_equals(
            "$.TranscriptionJobDetails.TranscriptionJob.TranscriptionJobStatus", "COMPLETED"
        )
        transcription_failed = sfn.Condition.string_equals(
            "$.TranscriptionJobDetails.TranscriptionJob.TranscriptionJobStatus", "FAILED"
        )

        translation_failed = sfn.Fail(self, "TranslationFailed", 
            cause="Transcription did not complete",
            error="TranscriptionFailed"
        )

        translate_task = tasks.CallAwsService(self, "Translate",
            service="translate",
            action="translateText",
            parameters={
                "SourceLanguageCode.$": "$.TranscriptionJobDetails.TranscriptionJob.LanguageCode",
                "TargetLanguageCode": "en",
                "Text.$": "$.TranscriptionJobDetails.TranscriptionJob.Transcript.TranscriptFileUri",
            },
            iam_resources=["*"],
            result_path="$.TranslatedText",
        )

        polly_task = tasks.CallAwsService(self, "Polly",
            service="polly",
            action="startSpeechSynthesisTask",
            parameters={
                "OutputFormat": "mp3",
                "OutputS3BucketName.$": "$.requestParameters.bucketName",
                "OutputS3KeyPrefix": "translations/",
                "Text.$": "$.TranslatedText.TranslatedText",
                "VoiceId": "Joanna",
            },
            iam_resources=["*"]
        )

        # Define the state machine
        definition = start_transcribe_task.next(
            wait_state.next(get_transcription_task)
        ).next(
            check_transcription_status
                .when(transcription_complete, translate_task.next(polly_task))
                .when(transcription_failed, translation_failed)
                .otherwise(wait_state.next(get_transcription_task))
        )

        state_machine = sfn.StateMachine(self, "Statemachine",
            definition=sfn.Chain.start(definition),
            role=sfn_role
        )

        # EventBridge Rule to trigger Step Function
        rule = events.Rule(self, "Rule",
            event_pattern={
                "source": ["aws.s3"],
                "detail": {
                    "eventSource": ["s3.amazonaws.com"],
                    "eventName": ["PutObject"],
                    "requestParameters": {
                        "bucketName": [bucket.bucket_name]
                    },
                    "requestParameters": {
                        "key": [{
                            "prefix": "translations/",
                            "anything-but": "translations/"
                        }]
                    }
                }
            }
        )
        rule.add_target(targets.SfnStateMachine(state_machine))
