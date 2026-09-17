"""Copy this file, rename it, and edit only the Strategy class."""


class Strategy:
    def reset(self, game_info):
        """Called once when this strategy is attached to a game."""
        self.next_channel = 1

    def next_action(self, observation):
        """Return exactly one move, measure, or clear action."""
        action = {"type": "measure", "channel": self.next_channel}
        self.next_channel = self.next_channel % 20 + 1
        return action
