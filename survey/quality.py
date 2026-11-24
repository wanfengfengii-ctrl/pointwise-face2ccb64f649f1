from dataclasses import dataclass

from survey.observations import Observation


@dataclass(frozen=True)
class QualityDisposition:
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.reason is None


def classify_observation(observation: Observation) -> QualityDisposition:
    if observation.quality == 'fail':
        return QualityDisposition('survey_flag')
    if not observation.instrument_ok:
        return QualityDisposition('instrument_check')
    return QualityDisposition()
