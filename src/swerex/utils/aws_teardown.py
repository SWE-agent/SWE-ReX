import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.waiter import WaiterError

"""
AWS Resource Cleanup Utility

This script automates the cleanup of AWS resources that were created by the SWE-REX AWS deployment process.
All resources are tagged with the 'origin=swe-rex-deployment-auto' tag to identify them as part of the SWE-REX deployment. These resources are removed by this script.

Resources handled:
- ECS Clusters (including running tasks)
- ECS Task Definitions
- Security Groups
- IAM Roles

Usage:
    python -m swerex.utils.aws_teardown

The script will preview all resources to be deleted and request confirmation before proceeding.
Each step is handled independently, allowing for partial cleanup if errors occur.
"""


def get_confirmation(message: str) -> bool:
    """
    Request user confirmation before proceeding with destructive actions.

    Args:
        message: The confirmation message to display to the user

    Returns:
        bool: True if user confirms, False otherwise
    """
    response = input(f"\n{message}\nDo you want to continue? (y/n): ").lower().strip()
    return response == "y"


def has_target_tag(tags: list[dict]) -> bool:
    """
    Check if a resource has the SWE-REX deployment tag.

    Args:
        tags: List of tag dictionaries from AWS resource

    Returns:
        bool: True if the target tag is present
    """
    return any(
        tag.get("key", tag.get("Key", "")) == "origin"
        and tag.get("value", tag.get("Value", "")) == "swe-rex-deployment-auto"
        for tag in tags
    )


def delete_iam_roles() -> None:
    """
    Delete all tagged IAM roles and their attached policies.
    Handles pagination for large numbers of roles.
    """
    iam = boto3.client("iam")
    paginator = iam.get_paginator("list_roles")

    # Preview roles to be deleted
    roles_to_delete = []
    for page in paginator.paginate():
        for role in page["Roles"]:
            tags = iam.list_role_tags(RoleName=role["RoleName"])["Tags"]
            if has_target_tag(tags):
                roles_to_delete.append(role["RoleName"])

    if not roles_to_delete:
        print("No IAM roles found to delete.")
        return

    confirmation_msg = "The following IAM roles will be deleted:\n" + "\n".join(f"- {role}" for role in roles_to_delete)
    if not get_confirmation(confirmation_msg):
        print("Skipping IAM role deletion.")
        return

    for role_name in roles_to_delete:
        try:
            print(f"Cleaning up IAM role: {role_name}")
            iam.delete_role(RoleName=role_name)
        except ClientError as e:
            print(f"Error processing role {role_name}: {str(e)}")


def delete_task_definitions() -> None:
    """
    Deregister all tagged ECS task definitions.
    Task definitions are not actually deleted but marked as INACTIVE.
    """
    ecs = boto3.client("ecs")
    paginator = ecs.get_paginator("list_task_definitions")

    # Preview task definitions to be deleted
    tasks_to_delete = []
    for page in paginator.paginate():
        for task_def_arn in page["taskDefinitionArns"]:
            tags = ecs.list_tags_for_resource(resourceArn=task_def_arn)["tags"]
            if has_target_tag(tags):
                tasks_to_delete.append(task_def_arn)

    if not tasks_to_delete:
        print("No task definitions found to delete.")
        return

    confirmation_msg = "The following task definitions will be deregistered:\n" + "\n".join(
        f"- {task}" for task in tasks_to_delete
    )
    if not get_confirmation(confirmation_msg):
        print("Skipping task definition deletion.")
        return

    for task_def_arn in tasks_to_delete:
        try:
            print(f"Deregistering task definition: {task_def_arn}")
            ecs.deregister_task_definition(taskDefinition=task_def_arn)
        except ClientError as e:
            print(f"Error processing task definition {task_def_arn}: {str(e)}")


def delete_ecs_clusters() -> None:
    """
    Delete all tagged ECS clusters and their running tasks.
    Waits for tasks to stop before attempting cluster deletion.
    """
    ecs = boto3.client("ecs")

    # Preview clusters to be deleted
    clusters = ecs.list_clusters()["clusterArns"]
    clusters_to_delete = []
    for cluster_arn in clusters:
        tags = ecs.list_tags_for_resource(resourceArn=cluster_arn)["tags"]
        if has_target_tag(tags):
            clusters_to_delete.append(cluster_arn)

    if not clusters_to_delete:
        print("No ECS clusters found to delete.")
        return

    confirmation_msg = "The following ECS clusters will be deleted:\n" + "\n".join(
        f"- {cluster}" for cluster in clusters_to_delete
    )
    if not get_confirmation(confirmation_msg):
        print("Skipping ECS cluster deletion.")
        return

    for cluster_arn in clusters_to_delete:
        try:
            print(f"Deleting ECS cluster: {cluster_arn}")
            # Stop all tasks in the cluster using pagination
            paginator = ecs.get_paginator("list_tasks")
            for page in paginator.paginate(cluster=cluster_arn):
                tasks = page["taskArns"]
                for task in tasks:
                    print(f"Stopping task: {task}")
                    ecs.stop_task(cluster=cluster_arn, task=task)

            # Wait for tasks to stop before deleting cluster
            waiter = ecs.get_waiter("tasks_stopped")
            try:
                waiter.wait(cluster=cluster_arn)
            except WaiterError:
                print(f"Warning: Timeout waiting for tasks to stop in cluster {cluster_arn}")

            # Delete the cluster
            ecs.delete_cluster(cluster=cluster_arn)
        except ClientError as e:
            print(f"Error processing cluster {cluster_arn}: {str(e)}")


def delete_security_groups() -> None:
    """
    Delete all tagged security groups.
    Removes all ingress and egress rules before deletion to handle dependencies.
    """
    ec2 = boto3.client("ec2")

    # Preview security groups to be deleted
    security_groups = ec2.describe_security_groups()["SecurityGroups"]
    sgs_to_delete = []
    for sg in security_groups:
        tags = sg.get("Tags", [])
        if has_target_tag(tags):
            sgs_to_delete.append(f"{sg['GroupId']} ({sg.get('GroupName', 'No Name')})")

    if not sgs_to_delete:
        print("No security groups found to delete.")
        return

    confirmation_msg = "The following security groups will be deleted:\n" + "\n".join(f"- {sg}" for sg in sgs_to_delete)
    if not get_confirmation(confirmation_msg):
        print("Skipping security group deletion.")
        return

    for sg in security_groups:
        try:
            if has_target_tag(sg.get("Tags", [])):
                print(f"Deleting security group: {sg['GroupId']}")
                # Remove all inbound rules first
                if sg.get("IpPermissions"):
                    ec2.revoke_security_group_ingress(GroupId=sg["GroupId"], IpPermissions=sg["IpPermissions"])
                # Remove all outbound rules
                if sg.get("IpPermissionsEgress"):
                    ec2.revoke_security_group_egress(GroupId=sg["GroupId"], IpPermissions=sg["IpPermissionsEgress"])
                # Delete the security group
                ec2.delete_security_group(GroupId=sg["GroupId"])
        except ClientError as e:
            print(f"Error processing security group {sg['GroupId']}: {str(e)}")


def main():
    """
    Orchestrate the cleanup of all AWS resources tagged with origin=swe-rex-deployment-auto.

    Process:
    1. Configure AWS clients with appropriate timeouts
    2. Preview all resources that will be affected
    3. Request user confirmation
    4. Delete resources in dependency order:
       - ECS clusters (and tasks)
       - Task definitions
       - Security groups
       - IAM roles
    """
    print("Starting cleanup of AWS resources tagged with origin=swe-rex-deployment-auto; this may take a while...")

    try:
        # Fix the Config instantiation
        config = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
        ecs = boto3.client("ecs", config=config)
        iam = boto3.client("iam", config=config)
        ec2 = boto3.client("ec2", config=config)

        # Get clusters and their tasks using pagination with timeout
        clusters = []
        try:
            clusters = ecs.list_clusters()["clusterArns"]
        except ClientError as e:
            print(f"Warning: Failed to list ECS clusters: {e}")
            clusters = []

        cluster_info = []
        for cluster_arn in clusters:
            try:
                tags = ecs.list_tags_for_resource(resourceArn=cluster_arn)["tags"]
                if has_target_tag(tags):
                    task_count = 0
                    paginator = ecs.get_paginator("list_tasks")
                    for page in paginator.paginate(cluster=cluster_arn, PaginationConfig={"MaxItems": 100}):
                        task_count += len(page["taskArns"])
                    cluster_name = cluster_arn.split("/")[-1]
                    cluster_info.append(f"  - Cluster: {cluster_name} ({task_count} running tasks)")
            except ClientError as e:
                print(f"Warning: Failed to process cluster {cluster_arn}: {e}")
                continue

        # Get task definitions
        task_defs = []
        paginator = ecs.get_paginator("list_task_definitions")
        for page in paginator.paginate():
            for task_def_arn in page["taskDefinitionArns"]:
                tags = ecs.list_tags_for_resource(resourceArn=task_def_arn)["tags"]
                if has_target_tag(tags):
                    task_name = task_def_arn.split("/")[-1]
                    task_defs.append(f"  - {task_name}")

        # Get IAM roles
        roles = []
        paginator = iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for role in page["Roles"]:
                tags = iam.list_role_tags(RoleName=role["RoleName"])["Tags"]
                if has_target_tag(tags):
                    roles.append(f"  - {role['RoleName']}")

        # Get security groups
        security_groups = []
        for sg in ec2.describe_security_groups()["SecurityGroups"]:
            tags = sg.get("Tags", [])
            if has_target_tag(tags):
                security_groups.append(f"  - {sg['GroupId']} ({sg.get('GroupName', 'No Name')})")

        # Build detailed confirmation message
        confirmation_msg = "The following AWS resources will be deleted:\n\n"

        if cluster_info:
            confirmation_msg += f"ECS Clusters ({len(cluster_info)}):\n" + "\n".join(cluster_info) + "\n\n"

        if task_defs:
            confirmation_msg += f"Task Definitions ({len(task_defs)}):\n" + "\n".join(task_defs) + "\n\n"

        if security_groups:
            confirmation_msg += f"Security Groups ({len(security_groups)}):\n" + "\n".join(security_groups) + "\n\n"

        if roles:
            confirmation_msg += f"IAM Roles ({len(roles)}):\n" + "\n".join(roles) + "\n\n"

        confirmation_msg += "This action cannot be undone."

        if not get_confirmation(confirmation_msg):
            print("Cleanup cancelled.")
            return

        # Order matters due to dependencies
        print("\nStopping and deleting ECS tasks and clusters...")
        delete_ecs_clusters()

        print("\nDeregistering task definitions...")
        delete_task_definitions()

        print("\nDeleting security groups...")
        delete_security_groups()

        print("\nCleaning up IAM roles...")
        delete_iam_roles()

        print("\nCleanup complete!")
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")


if __name__ == "__main__":
    main()
