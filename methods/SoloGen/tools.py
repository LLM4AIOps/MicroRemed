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
