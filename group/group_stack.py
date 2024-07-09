from aws_cdk import (
    aws_s3 as s3,
    Stack,
    Duration,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_s3_notifications as s3n,
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

        # IAM Role for Step Functions to interact with other services
        bucket.grant_read_write(sfn_role)
        sfn_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonTranscribeFullAccess")
        )
        sfn_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("TranslateFullAccess")
        )
        sfn_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonPollyFullAccess")
        )
        sfn_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3ReadOnlyAccess")
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
                    "MediaFileUri.$": "States.Format('s3://{}/{}', $.detail.requestParameters.bucketName,  $.detail.requestParameters.key)"
                },
                "OutputBucketName.$": "$.detail.requestParameters.bucketName"
            },
            iam_resources=["*"],
            result_path="$.TranscriptionJobDetails",
        )

        wait_state = sfn.Wait(self, "WaitForTranscription",
            time=sfn.WaitTime.duration(Duration.seconds(30))
        )

        get_transcription_task = tasks.CallAwsService(self, "GetTranscription",
            service="transcribe",
            action="getTranscriptionJob",
            parameters={
                "TranscriptionJobName.$": "$.TranscriptionJobDetails.TranscriptionJobName"
            },
            iam_resources=["*"],
            result_path="$.TranscriptionJobDetails",
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
            action="synthesizeSpeech",
            parameters={
                "Text.$": "$.TranslatedText.TranslatedText",
                "OutputFormat": "mp3",
                "VoiceId": "Joanna",
                "OutputS3BucketName.$": "$.requestParameters.bucketName",
                "OutputS3KeyPrefix": "translations/",
                #"S3Bucket.$": "$.detail.requestParameters.bucketName",
                #"S3Key.$": "States.Format('translations/{}.mp3', $.detail.requestParameters.key.replace('/', '_'))"
            },
            iam_resources=["*"]
        )

        # Define the state machine
        definition = start_transcribe_task.next(wait_state).next(get_transcription_task).next(translate_task).next(polly_task)
        
        state_machine = sfn.StateMachine(self, "StateMachine",
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
                    }
                }
            }
        )
        rule.add_target(targets.SfnStateMachine(state_machine))

        ## Output the State Machine ARN
        #core.CfnOutput(
        #    self,
        #    "StateMachineARN",
        #    value=state_machine.state_machine_arn,
        #    description="The ARN of the State Machine",
        #)

        # Output the S3 Bucket Name
        #core.CfnOutput(
        #    self,
        #    "S3BucketName",
        #    value=bucket.bucket_name,
        #    description="The name of the S3 bucket",
        #)
