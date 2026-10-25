from app.integration.windiq_api.schemas import MastDto, SiteDto, TurbineDto
from app.repositories import reference_repo
from tests.api_samples import MAST, SITE, TURBINE


def save_samples(session, site=SITE):
    reference_repo.save(
        session, MastDto.model_validate(MAST), TurbineDto.model_validate(TURBINE), SiteDto.model_validate(site)
    )


def test_load_returns_none_before_first_sync(db_session):
    assert reference_repo.load(db_session) is None


def test_saved_reference_data_can_be_loaded(db_session):
    save_samples(db_session)

    loaded = reference_repo.load(db_session)

    assert loaded.mast.measurement_height_m == 100.0
    assert loaded.turbine.power_curve[12].power_kw == 3520.0
    assert loaded.site.version == 44


def test_newer_state_replaces_older(db_session):
    save_samples(db_session, site={**SITE, "version": 43, "losses": {**SITE["losses"], "wake": 0.06}})

    save_samples(db_session)

    loaded = reference_repo.load(db_session)
    assert (loaded.site.version, loaded.site.losses.wake) == (44, 0.05)
