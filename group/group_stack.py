from aws_cdk import (
    aws_s3 as s3,
    Stack,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_s3_notifications as s3n,
    aws_events as events,
    aws_events_targets as targets
)
from constructs import Construct

class GroupStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
         # S3 bucket for audio files and translations

        bucket = s3.Bucket(self, "TranslationBucket")
        

         # IAM Role for Step Functions to interact with other services
        role = iam.Role(self, "StepFunctionsRole",
                        assumed_by=iam.ServicePrincipal("states.amazonaws.com"))
        
        role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaRole"))
        role.add_to_policy(iam.PolicyStatement(
            resources=["*"],
            actions=[
                "transcribe:StartTranscriptionJob",
                "transcribe:GetTranscriptionJob",
                "translate:TranslateText",
                "polly:SynthesizeSpeech"
            ]
        ))

        # Step Functions Tasks
        transcribe_task = tasks.CallAwsService(self, "Transcribe",
            service="transcribe",
            action="startTranscriptionJob",
            parameters={
                "TranscriptionJobName": sfn.JsonPath.string_at("$.detail.requestParameters.key"),
                "LanguageCode": "auto",
                "MediaFormat": "mp3",
                "Media": {
                    "MediaFileUri": sfn.JsonPath.string_at("States.Format('s3://{}/{}', $.detail.requestParameters.bucketName, $.detail.requestParameters.key)")
                },
                "OutputBucketName": sfn.JsonPath.string_at("$.detail.requestParameters.bucketName")
            },
            iam_resources=["*"]
        )

        translate_task = tasks.CallAwsService(self, "Translate",
            service="translate",
            action="translateText",
            parameters={
                "Text": sfn.JsonPath.string_at("$.TranscriptionJob.Transcript.TranscriptFileUri"),
                "SourceLanguageCode": sfn.JsonPath.string_at("$.TranscriptionJob.LanguageCode"),
                "TargetLanguageCode": "en"
            },
            iam_resources=["*"]
        )

        polly_task = tasks.CallAwsService(self, "Polly",
            service="polly",
            action="synthesizeSpeech",
            parameters={
                "Text": sfn.JsonPath.string_at("$.TranslateText.TranslatedText"),
                "OutputFormat": "mp3",
                "VoiceId": "Joanna",
                "OutputS3BucketName": sfn.JsonPath.string_at("$.detail.requestParameters.bucketName"),
                "OutputS3KeyPrefix": "translations/"
            },
            iam_resources=["*"]
        )

        # Define the state machine
        definition = transcribe_task.next(translate_task).next(polly_task)
        
        state_machine = sfn.StateMachine(self, "StateMachine",
            definition=sfn.Chain.start(definition),
            role=role
        )

        # EventBridge Rule to trigger Step Function
        rule = events.Rule(self, "Rule",
            event_pattern={
                "source": ["aws.s3"],
               # "detailType": ["AWS API Call via CloudTrail"],
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

        # Grant necessary permissions
        bucket.grant_read_write(role)
