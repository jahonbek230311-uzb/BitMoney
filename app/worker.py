import logging, threading, time
from sqlalchemy import select, update
from judge.engine import TestInput, judge
from judge.runners import JudgeSystemError
from .models import Problem, Submission, TestCase, TestResult
from .timeutil import now

log = logging.getLogger("cpjudge.worker")
docker_slots = threading.BoundedSemaphore(3)  # cap concurrent sandboxes


def tests_for(db, problem_id):
    rows = db.scalars(select(TestCase).where(TestCase.problem_id == problem_id, TestCase.validated.is_(True))
                      .order_by(TestCase.ordinal)).all()
    return rows, [TestInput(t.id, t.input_data, t.expected_output) for t in rows]


def judge_submission(db, runner, sub):
    problem = db.get(Problem, sub.problem_id)
    _, tests = tests_for(db, problem.id)
    if not tests:
        sub.verdict, sub.compile_log = "SE", "Problem has no validated tests."
        return
    try:
        with docker_slots:
            res = judge(runner, sub.language, sub.source, tests, problem.time_limit_ms / 1000.0,
                        problem.memory_limit_mb, problem.checker_mode)
    except (JudgeSystemError, OSError) as e:
        sub.verdict, sub.compile_log = "SE", "Judge unavailable (is Docker running?): " + str(e)[:300]
        return
    sub.verdict, sub.compile_log = res.verdict, res.compile_log[:8000]
    sub.time_ms, sub.memory_kb, sub.passed, sub.total = res.max_time_ms, res.max_memory_kb, res.passed, res.total
    for tv in res.tests:
        db.add(TestResult(submission_id=sub.id, test_case_id=tv.test_id, verdict=tv.verdict,
                          time_ms=tv.time_ms, memory_kb=tv.memory_kb))


def worker_loop(session_factory, runner, stop: threading.Event):
    while not stop.is_set():
        try:
            with session_factory() as db:
                sub = db.scalar(select(Submission).where(Submission.verdict == "PENDING").order_by(Submission.id).limit(1))
                if not sub:
                    time.sleep(0.5)
                    continue
                sub.verdict = "JUDGING"
                db.commit()
                try:
                    judge_submission(db, runner, sub)
                except Exception as e:  # never leave a submission stuck
                    log.exception("judging failed")
                    sub.verdict, sub.compile_log = "SE", "Internal judge error: " + type(e).__name__
                sub.judged_at = now()
                db.commit()
        except Exception:
            log.exception("worker loop error")
            time.sleep(2)


def requeue_stuck(session_factory):
    with session_factory() as db:
        db.execute(update(Submission).where(Submission.verdict == "JUDGING").values(verdict="PENDING"))
        db.commit()
