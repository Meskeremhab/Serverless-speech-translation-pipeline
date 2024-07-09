import aws_cdk as core
import aws_cdk.assertions as assertions

from group.group_stack import GroupStack

# example tests. To run these tests, uncomment this file along with the example
# resource in group/group_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = GroupStack(app, "group")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
