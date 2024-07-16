from aws_cdk import (
    aws_s3 as s3,
    aws_cloudtrail as cloudtrail,
    aws_events_targets as targets,
    aws_stepfunctions_tasks as tasks,
    aws_events as events,
    Stack,
    Duration,
    RemovalPolicy,
    aws_iam as iam,
    aws_stepfunctions as sfn,
)
from constructs import Construct

class GroupStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
      # Create S3 bucket
        bucket = s3.Bucket(self, "TranslationBucket", 
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True  # This ensures the bucket is emptied on deletion
        )
        
        # Create CloudTrail trail
        trail = cloudtrail.Trail(self, "CloudTrail",
            bucket=bucket,
            is_multi_region_trail=False,
        )
        trail.add_s3_event_selector(
            s3_selector=[cloudtrail.S3EventSelector(bucket=bucket, object_prefix="translations/")],
            include_management_events=True,
        )

        # Create IAM role for Step Functions
        sfn_role = iam.Role(
            self,
            "StepFunctionsRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )

        # IAM Role for Step Functions to interact with other services
        bucket.grant_read_write(sfn_role)
        for policy in ["AmazonTranscribeFullAccess", "TranslateFullAccess", "AmazonPollyFullAccess", "AmazonS3ReadOnlyAccess"]:
            sfn_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name(policy))
       
        # Step Functions Tasks
        start_transcribe_task = tasks.CallAwsService(self, "StartTranscription",
            service="transcribe",
            action="startTranscriptionJob",
            parameters={
                "TranscriptionJobName.$": "States.Format('TranscriptionJob-{}', $$.Execution.Name)",
                "IdentifyLanguage": True,  
                "Media": {
                    "MediaFileUri.$": "States.Format('s3://{}/{}', $.detail.requestParameters.bucketName, $.detail.requestParameters.key)"
                },
                "OutputBucketName.$": "$.detail.requestParameters.bucketName"
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

        read_s3_object_task = tasks.CallAwsService(self, "ReadS3Object",
            service="s3",
            action="getObject",
            parameters={
                "Bucket.$": "States.ArrayGetItem(States.StringSplit($.TranscriptionJobDetails.TranscriptionJob.Transcript.TranscriptFileUri, '/'), 2)",
                "Key.$": "States.ArrayGetItem(States.StringSplit($.TranscriptionJobDetails.TranscriptionJob.Transcript.TranscriptFileUri, '/'), 3)",
            },
            iam_resources=["*"],
            result_selector={
                "FileContents.$": "States.StringToJson($.Body)"
            },
            result_path="$.TranscriptionText"
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
                "Text.$": "$.TranscriptionText.FileContents.results.transcripts[0].transcript",
            },
            iam_resources=["*"],
            result_path="$.TranslatedText",
        )

        polly_task = tasks.CallAwsService(self, "Polly",
            service="polly",
            action="startSpeechSynthesisTask",
            parameters={
                "OutputFormat": "mp3",
                "OutputS3BucketName.$": "$.detail.requestParameters.bucketName",
                "OutputS3KeyPrefix": "translations/",
                "Text.$": "$.TranslatedText.TranslatedText",
                "VoiceId": "Joanna",
            },
            iam_resources=["*"],
            result_path="$.PollyResult"
        )
    
        check_language_task = sfn.Choice(self, "CheckLanguage")
        is_english = sfn.Condition.string_equals("$.TranscriptionJobDetails.TranscriptionJob.LanguageCode", "en-US")

        wait_and_get_task = wait_state.next(get_transcription_task)

        # Define the state machine
        definition = start_transcribe_task.next(wait_and_get_task).next(
            check_transcription_status
                .when(transcription_complete, check_language_task
                    .when(is_english, sfn.Pass(self, "SkipProcessing"))
                    .otherwise(read_s3_object_task.next(translate_task.next(polly_task)))
                )
                .when(transcription_failed, translation_failed)
                .otherwise(wait_and_get_task)
        )

        state_machine = sfn.StateMachine(self, "Statemachine",
            definition=definition,
            role=sfn_role
        )
       
        #EventBridge Rule to trigger Step Function
        rule = events.Rule(self, "Rule",
            event_pattern={
                "source": ["aws.s3"],
                "detail_type": ["AWS API Call via CloudTrail"],
                "detail": {
                    "eventSource": ["s3.amazonaws.com"],
                    "eventName": ["PutObject"],
                    "requestParameters": {
                        "bucketName": [bucket.bucket_name],
                        "key": [{
                            "prefix": "translations/"
                        }]
                    }
                }
            }
        )
        rule.add_target(targets.SfnStateMachine(state_machine))