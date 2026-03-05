class MetricsPatch:
    _applied = False

    @classmethod
    def apply(cls):
        cls._applied = True
