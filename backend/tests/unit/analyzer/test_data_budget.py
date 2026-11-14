import threading
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.science.pipeline import ScienceDeps
from app.analyzer.validation.data_budget import DataBudget, DataBudgetError
from app.api.routes import availability
from app.schemas import JobStage

from .test_analysis_service import BLOB, deps, request


def fetcher(log=None):
    def fetch(first, last):
        if log is not None:
            log.append((first, last))
        return b"x" * (last - first + 1)
    return fetch


def test_every_byte_read_is_counted_per_job_and_per_session() -> None:
    budget = DataBudget(per_analysis_cap_bytes=1000, session_cap_bytes=5000)
    a, b = budget.start_job(), budget.start_job()
    fa, fb = budget.metered(fetcher(), a), budget.metered(fetcher(), b)
    assert len(fa(0, 99)) == 100 and len(fa(100, 249)) == 150 and len(fb(0, 49)) == 50
    assert (a.used_bytes, b.used_bytes) == (250, 50)
    assert budget.snapshot() == {"per_analysis_cap_bytes": 1000, "session_cap_bytes": 5000, "session_used_bytes": 300, "analyses_counted": 2}


def test_a_request_over_the_per_analysis_cap_is_refused_before_it_is_sent() -> None:
    log = []
    budget = DataBudget(per_analysis_cap_bytes=100, session_cap_bytes=10_000)
    job = budget.start_job()
    fetch = budget.metered(fetcher(log), job)
    fetch(0, 59)                                           # 60 of 100 bytes
    with pytest.raises(DataBudgetError) as exc:
        fetch(60, 119)                                     # would make 120
    assert exc.value.scope == "analysis" and "choose a smaller area" in str(exc.value) and exc.value.code == "data_budget"
    assert log == [(0, 59)]                                # the refused request never left
    assert job.refused is exc.value and job.used_bytes == 60
    assert len(fetch(60, 99)) == 40                        # the remaining allowance is still usable


def test_the_session_cap_spans_analyses() -> None:
    budget = DataBudget(per_analysis_cap_bytes=1000, session_cap_bytes=150)
    first = budget.metered(fetcher(), budget.start_job())
    first(0, 99)
    log = []
    second = budget.metered(fetcher(log), budget.start_job())
    with pytest.raises(DataBudgetError) as exc:
        second(0, 99)
    assert exc.value.scope == "session" and "session" in str(exc.value) and log == []
    assert len(second(0, 49)) == 50                        # what is left still works


def test_a_failed_fetch_gives_its_reservation_back() -> None:
    budget = DataBudget(per_analysis_cap_bytes=100, session_cap_bytes=100)
    job = budget.start_job()

    def broken(first, last):
        raise OSError("network down")
    with pytest.raises(OSError):
        budget.metered(broken, job)(0, 99)
    assert job.used_bytes == 0 and budget.snapshot()["session_used_bytes"] == 0
    assert len(budget.metered(fetcher(), job)(0, 99)) == 100                       # the full allowance is intact


def test_concurrent_reads_never_overshoot_the_cap() -> None:
    budget = DataBudget(per_analysis_cap_bytes=1000, session_cap_bytes=10_000)
    job = budget.start_job()
    fetch = budget.metered(fetcher(), job)
    ok, refused, gate = [], [], threading.Barrier(40)

    def worker():
        gate.wait()
        try:
            ok.append(len(fetch(0, 49)))                   # 50 bytes each, 40 threads want 2000
        except DataBudgetError:
            refused.append(1)
    threads = [threading.Thread(target=worker) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 20 and len(refused) == 20            # exactly the cap's worth succeeded
    assert job.used_bytes == 1000 and budget.snapshot()["session_used_bytes"] == 1000


def test_invalid_caps_are_rejected() -> None:
    with pytest.raises(ValueError):
        DataBudget(per_analysis_cap_bytes=0)


def used_by_one_analysis(tmp_path):
    budget = DataBudget(10**9, 10**9)
    svc = AnalysisService(deps(tmp_path / "probe"), budget=budget)
    svc.submit(request())
    svc.wait_idle()
    return budget.snapshot()["session_used_bytes"]


def test_an_analysis_over_the_per_analysis_cap_fails_with_data_budget(tmp_path) -> None:
    used = used_by_one_analysis(tmp_path)
    assert used > 0
    budget = DataBudget(per_analysis_cap_bytes=used - 1, session_cap_bytes=10**9)
    svc = AnalysisService(deps(tmp_path / "run"), budget=budget)
    job = svc.submit(request())
    svc.wait_idle()
    done = svc.get_job(job.id)
    assert done.stage == JobStage.failed and done.error_code == "data_budget"
    assert "limit of" in done.message and "smaller area" in done.message


def test_the_session_cap_fails_a_later_analysis_with_data_budget(tmp_path) -> None:
    used = used_by_one_analysis(tmp_path)
    budget = DataBudget(per_analysis_cap_bytes=10**9, session_cap_bytes=used + used // 2)
    svc = AnalysisService(deps(tmp_path / "run"), budget=budget)
    first = svc.submit(request(east=14.0))
    svc.wait_idle()
    second = svc.submit(request(east=13.0))                # a different area, so it is not reused
    svc.wait_idle()
    assert svc.get_job(first.id).stage == JobStage.completed
    again = svc.get_job(second.id)
    assert again.stage == JobStage.failed and again.error_code == "data_budget" and "session" in again.message


def test_without_a_budget_nothing_changes(tmp_path) -> None:
    svc = AnalysisService(deps(tmp_path))
    job = svc.submit(request())
    svc.wait_idle()
    assert svc.get_job(job.id).stage == JobStage.completed


def test_spectral_range_fetchers_are_counted_too(tmp_path) -> None:
    budget = DataBudget(10_000, 10_000)
    seen = []
    science = ScienceDeps(fetch_json=lambda u: {}, fetch_text=lambda u: "", range_fetcher_for=lambda url: (lambda a, b: seen.append((url, a, b)) or b"y" * (b - a + 1)))
    svc = AnalysisService(replace(deps(tmp_path), science=science), budget=budget)
    metered, meter = svc._metered_deps()
    assert len(metered.science.range_fetcher_for("https://example.test/cube.img")(0, 199)) == 200
    assert meter.used_bytes == 200 and seen == [("https://example.test/cube.img", 0, 199)]
    with pytest.raises(DataBudgetError):
        metered.science.range_fetcher_for("https://example.test/other.img")(0, 20_000)


def test_the_endpoint_reports_the_budget() -> None:
    budget = DataBudget(2 * 1024 * 1024, 8 * 1024 * 1024)
    budget.metered(fetcher(), budget.start_job())(0, 1023)
    app = FastAPI()
    app.include_router(availability.router, prefix="/api/v1")
    app.dependency_overrides[availability.get_budget] = lambda: budget
    body = TestClient(app).get("/api/v1/data-budget").json()
    assert body == {"per_analysis_cap_bytes": 2 * 1024 * 1024, "session_cap_bytes": 8 * 1024 * 1024, "session_used_bytes": 1024, "analyses_counted": 1}
