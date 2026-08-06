"""Provider-neutral calendar attendee and response contracts."""

from dataclasses import dataclass

_ROLES = {"CHAIR", "REQ-PARTICIPANT", "OPT-PARTICIPANT", "NON-PARTICIPANT"}
_RESPONSES = {"NEEDS-ACTION", "ACCEPTED", "DECLINED", "TENTATIVE"}


@dataclass(frozen=True, slots=True)
class CalendarAttendee:
    """One canonical participant identity and response state."""

    address: str
    display_name: str | None = None
    role: str = "REQ-PARTICIPANT"
    response: str = "NEEDS-ACTION"
    rsvp: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.address, str) or not self.address.strip():
            raise ValueError("address must be non-empty.")
        address = self.address.strip()
        if address.lower().startswith("mailto:"):
            address = address[7:]
        if any(char.isspace() or ord(char) < 32 for char in address):
            raise ValueError("address must not contain whitespace or controls.")
        if address.count("@") != 1 or address.startswith("@") or address.endswith("@"):
            raise ValueError("address must be an email address.")
        object.__setattr__(self, "address", address.lower())
        if self.display_name is not None:
            if not isinstance(self.display_name, str) or not self.display_name.strip():
                raise ValueError("display_name must be non-empty when supplied.")
            if any(ord(char) < 32 for char in self.display_name):
                raise ValueError("display_name must not contain control characters.")
        role = self.role.upper()
        if role not in _ROLES:
            raise ValueError("role is not a supported iCalendar attendee role.")
        object.__setattr__(self, "role", role)
        response = self.response.upper()
        if response not in _RESPONSES:
            raise ValueError("response is not a supported attendee response.")
        object.__setattr__(self, "response", response)
        if not isinstance(self.rsvp, bool):
            raise TypeError("rsvp must be a boolean.")

    @classmethod
    def from_ical(
        cls,
        address: str,
        *,
        display_name: str | None = None,
        role: str | None = None,
        response: str | None = None,
        rsvp: str | None = None,
    ) -> "CalendarAttendee":
        """Construct from an iCalendar ATTENDEE value and parameters."""
        return cls(
            address,
            display_name=display_name,
            role=role or "REQ-PARTICIPANT",
            response=response or "NEEDS-ACTION",
            rsvp=(rsvp or "FALSE").upper() == "TRUE",
        )


def canonical_attendees(
    attendees: tuple[CalendarAttendee, ...] | list[CalendarAttendee],
) -> tuple[CalendarAttendee, ...]:
    """Validate, de-duplicate and sort attendees by canonical address."""
    values = tuple(attendees)
    if any(not isinstance(value, CalendarAttendee) for value in values):
        raise TypeError("attendees must contain CalendarAttendee values.")
    if len({value.address for value in values}) != len(values):
        raise ValueError("attendees must not contain duplicate addresses.")
    return tuple(sorted(values, key=lambda value: value.address))
