print_playbook_function = {
    "type": "function",
    "function": {
        "name": "print_playbook",
        "description": "Print playbook code to remediate the current microservice anomaly.",
        "parameters": {
            "properties": {
                "code": {
                    "type": "string",
                    "description": "This playbook can be executed directly with ansible-playbook -i inventory.ini remediation.yaml to remediate the current microservice anomaly."
                },
            },
            "required": [
                "code"
            ]
        }
    }
}

probe_function = {
    "type": "function",
    "function": {
        "name": "probe_system",
        "description": "Output a series of cmd commands. If multiple commands are needed, separate them with ';' so they can be executed together. These commands will be run once to probe the target microservice system for the required information, and the results will be returned to facilitate subsequent playbook generation.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmds": {
                    "type": "string",
                    "description": "A series of cmd commands. If multiple commands are needed, separate them with ';' so they can be executed together."
                },
            },
            "required": [
                "cmds"
            ]
        }
    }
}
