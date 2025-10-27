import methods.ThinkRemed.coordinator
import methods.SoloGen.generator


def remediate(runtime_envs, namespace, root_cause, failure_category, remediate_method):
    if remediate_method == "ThinkRemed":
        return methods.ThinkRemed.coordinator.remediate_failure(runtime_envs, namespace, root_cause, failure_category)
    elif remediate_method == "SoloGen":
        return methods.SoloGen.generator.remediate_failure(runtime_envs, namespace, root_cause, failure_category)
