"""Small example: patrol a grid and measure all channels at each point."""


class Strategy:
    def reset(self, game_info):
        coordinates = (-1200, -600, 0, 600, 1200)
        self.points = [(x, y) for y in coordinates for x in coordinates]
        self.point_index = 0
        self.channel = 1
        self.need_move = True

    def next_action(self, observation):
        if self.need_move:
            x, y = self.points[self.point_index % len(self.points)]
            self.need_move = False
            return {"type": "move", "x": x, "y": y}

        action = {"type": "measure", "channel": self.channel}
        self.channel += 1
        if self.channel > 20:
            self.channel = 1
            self.point_index += 1
            self.need_move = True
        return action
