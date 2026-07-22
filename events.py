class EventBus:
    def __init__(self):
        self._handlers = {}

    def on(self, event, handler):
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    def off(self, event, handler):
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    def emit(self, event, **data):
        for handler in self._handlers.get(event, []):
            handler(data)
