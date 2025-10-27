from chaos import check_status


def verify_status(namespace, label, type):
    return check_status.check(namespace, label, type)
