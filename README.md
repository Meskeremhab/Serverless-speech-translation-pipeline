Serverless speech translation pipeline


Scenario
If you remember your application process to IE University (and if it hasn't changed since I went through it), there is one step in which you have to record yourself on camera answering to some predefined questions. IE university wants to improve the user experience of the process and will now allow students to answer the questions in any language of their choice. 



As I'm sure you have seen, IE is home for students all over the world, and employees from the admissions department don't speak every single language, so for this project to succeed they are in need of a tool that translates the recordings of the students from any language to english. They already own a software that separates the video from the audio, so you don't have to worry about that.



Your task is to implement a serverless translation pipeline using AWS services that translates to english any audio file that is uploaded to an S3 bucket



Requirements
The newly generated audio file must be stored in the same S3 bucket where files are uploaded, under a path called "translations"
The application must be implemented using Amazon Translate, Amazon Transcribe, Amazon Polly and AWS Step Functions
If you implement the solution using IaC, it must be through CDK and you can only use L1 and L2 constructs.
You must interact with the AI services using their appropriate actions directly in AWS Step Functions.


Considerations
Amazon Transcribe's free tier includes only 60 minutes per month, so don't test the application with long voice files
When configuring the rule in Event Bridge, do so in a way that it is not triggered when files are put in the /translations path, otherwise you will enter in and endless loop
You cannot assume that I'll have in my account a trail that captures write events to S3
