"""The analyzer's in-process event bus delivers each event to its type's subscribers, in order (#139)."""
from dataclasses import dataclass
import unittest

from music_analyzer.infrastructure.event_bus import InProcessEventBus


@dataclass(frozen=True)
class Saved:
    name: str


@dataclass(frozen=True)
class Deleted:
    name: str


class InProcessEventBusTests(unittest.TestCase):
    def test_each_subscriber_of_the_event_type_hears_it_in_subscription_order(self):
        bus, heard = InProcessEventBus(), []
        bus.subscribe(Saved, lambda event: heard.append(('first', event)))
        bus.subscribe(Deleted, lambda event: heard.append(('deleted', event)))
        bus.subscribe(Saved, lambda event: heard.append(('second', event)))

        bus.publish(Saved('a'))

        self.assertEqual([('first', Saved('a')), ('second', Saved('a'))], heard)

    def test_an_event_nobody_subscribed_to_is_dropped(self):
        InProcessEventBus().publish(Deleted('a'))


if __name__ == '__main__':
    unittest.main()
