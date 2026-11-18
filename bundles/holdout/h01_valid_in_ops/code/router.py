"""Ticket router (c1)."""

ESCALATE_AFTER = minutes(25)


def route(ticket):
    if ticket.get("category") is None:
        # ref: R1
        return "manual_review"
    elif ticket.get("priority") in ("urgent",):
        # ref: R2
        return "priority_queue"
    elif ticket.get("wait_time", 0) >= ESCALATE_AFTER:
        # ref: R3
        return "escalation"
    else:
        # ref: R9
        return "normal_queue"
