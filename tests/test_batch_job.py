# pylint: disable=protected-access
from unittest.mock import ANY, call, Mock, patch

import pytest

from marge.batch_job import BatchMergeJob
from marge.job import CannotMerge, SkipMerge, MergeJobOptions


def get_batch_merge_job(**batch_merge_kwargs):
    params = {
        'api': Mock(),
        'user': Mock(),
        'project': Mock(),
        'merge_requests': Mock(),
        'repo': Mock(),
        'options': MergeJobOptions.default(),
    }
    params.update(batch_merge_kwargs)
    return BatchMergeJob(**params)


def test_remove_batch_branch():
    repo = Mock()
    batch_merge_job = get_batch_merge_job(repo=repo)
    batch_merge_job.remove_batch_branch()
    repo.remove_branch.assert_called_once_with(
        BatchMergeJob.BATCH_BRANCH_NAME,
    )


def test_close_batch_mr():
    with patch('marge.batch_job.MergeRequest') as mr_class:
        batch_mr = Mock()
        mr_class.search.return_value = [batch_mr]

        batch_merge_job = get_batch_merge_job()
        batch_merge_job.close_batch_mr()

        params = {
            'author_id': batch_merge_job._user.id,
            'labels': BatchMergeJob.BATCH_BRANCH_NAME,
            'state': 'opened',
            'order_by': 'created_at',
            'sort': 'desc',
        }
        mr_class.search.assert_called_once_with(
            api=ANY,
            project_id=ANY,
            params=params,
        )
        batch_mr.close.assert_called_once()


def test_create_batch_mr():
    with patch('marge.batch_job.MergeRequest') as mr_class:
        batch_mr = Mock()
        mr_class.create.return_value = batch_mr

        batch_merge_job = get_batch_merge_job()
        target_branch = 'master'
        r_batch_mr = batch_merge_job.create_batch_mr(target_branch)

        params = {
            'source_branch': BatchMergeJob.BATCH_BRANCH_NAME,
            'target_branch': target_branch,
            'title': 'Marge Bot Batch MR - DO NOT TOUCH',
            'labels': BatchMergeJob.BATCH_BRANCH_NAME,
        }
        mr_class.create.assert_called_once_with(
            api=ANY,
            project_id=ANY,
            params=params,
        )
        assert r_batch_mr is batch_mr


def test_unassign_from_mr():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock()

    # when we are not the author
    batch_merge_job.unassign_from_mr(merge_request)
    merge_request.assign_to.assert_called_once_with(merge_request.author_id)

    # when we are the author
    merge_request.author_id = batch_merge_job._user.id
    batch_merge_job.unassign_from_mr(merge_request)
    merge_request.unassign.assert_called_once()


@pytest.mark.skip('Move to abstract job')
def test_get_source_project_when_is_target_project():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock()
    merge_request.source_project_id = batch_merge_job._project.id
    r_source_project = batch_merge_job.get_source_project(merge_request)
    assert r_source_project is batch_merge_job._project


@pytest.mark.skip('Move to abstract job')
def test_get_source_project_when_is_fork():
    with patch('marge.batch_job.Project') as project_class:
        batch_merge_job = get_batch_merge_job()
        merge_request = Mock()
        r_source_project = batch_merge_job.get_source_project(merge_request)

        project_class.fetch_by_id.assert_called_once_with(
            merge_request.source_project_id,
            api=batch_merge_job._api,
        )
        assert r_source_project is not batch_merge_job._project
        assert r_source_project is project_class.fetch_by_id.return_value


@pytest.mark.skip('Move to abstract job')
def test_get_mr_ci_status():
    with patch('marge.batch_job.Commit') as commit_class:
        commit_class.fetch_by_id.return_value = Mock(status='success')
        batch_merge_job = get_batch_merge_job()
        merge_request = Mock()

        r_ci_status = batch_merge_job.get_mr_ci_status(merge_request)

        commit_class.fetch_by_id.assert_called_once_with(
            merge_request.source_project_id,
            merge_request.sha,
            batch_merge_job._api,
        )
        assert r_ci_status == 'success'


def test_get_mrs_with_common_target_branch():
    master_mrs = [
        Mock(target_branch='master'),
        Mock(target_branch='master'),
    ]
    non_master_mrs = [
        Mock(target_branch='non_master'),
        Mock(target_branch='non_master'),
    ]
    batch_merge_job = get_batch_merge_job(
        merge_requests=non_master_mrs + master_mrs,
    )
    r_maser_mrs = batch_merge_job.get_mrs_with_common_target_branch('master')
    assert r_maser_mrs == master_mrs


def test_ensure_mergeable_mr_not_assigned():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock(
        state='opened',
        work_in_progress=False,
        squash=False,
    )
    with pytest.raises(SkipMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)
    assert exc_info.value.reason == 'It is not assigned to me anymore!'


def test_ensure_mergeable_mr_state_not_ok():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock(
        assignee_id=batch_merge_job._user.id,
        state='merged',
        work_in_progress=False,
        squash=False,
    )
    with pytest.raises(CannotMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)
    assert exc_info.value.reason == 'The merge request is already merged!'


def test_ensure_mergeable_mr_not_approved():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock(
        assignee_id=batch_merge_job._user.id,
        state='opened',
        work_in_progress=False,
        squash=False,
    )
    merge_request.fetch_approvals.return_value.sufficient = False
    with pytest.raises(CannotMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)

    merge_request.fetch_approvals.assert_called_once()
    assert 'Insufficient approvals' in str(exc_info.value)


def test_ensure_mergeable_mr_wip():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock(
        assignee_id=batch_merge_job._user.id,
        state='opened',
        work_in_progress=True,
    )
    merge_request.fetch_approvals.return_value.sufficient = True
    with pytest.raises(CannotMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)

    assert exc_info.value.reason == "Sorry, I can't merge requests marked as Work-In-Progress!"


def test_ensure_mergeable_mr_squash_and_trailers():
    batch_merge_job = get_batch_merge_job(options=MergeJobOptions.default(add_reviewers=True))
    merge_request = Mock(
        assignee_id=batch_merge_job._user.id,
        state='opened',
        work_in_progress=False,
        squash=True,
    )
    merge_request.fetch_approvals.return_value.sufficient = True
    with pytest.raises(CannotMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)

    assert (
        exc_info.value.reason == "Sorry, merging requests marked as auto-squash would ruin my commit tagging!"
    )


@patch.object(BatchMergeJob, 'get_mr_ci_status')
def test_ensure_mergeable_mr_ci_not_ok(bmj_get_mr_ci_status):
    batch_merge_job = get_batch_merge_job()
    batch_merge_job._project.only_allow_merge_if_pipeline_succeeds = True
    bmj_get_mr_ci_status.return_value = 'failed'
    merge_request = Mock(
        assignee_id=batch_merge_job._user.id,
        state='opened',
        work_in_progress=False,
        squash=False,
    )
    merge_request.fetch_approvals.return_value.sufficient = True
    with pytest.raises(CannotMerge) as exc_info:
        batch_merge_job.ensure_mergeable_mr(merge_request)

    assert exc_info.value.reason == 'This MR has not passed CI'


def test_fuse_using_rebase():
    batch_merge_job = get_batch_merge_job(options=MergeJobOptions.default(use_merge_strategy=False))
    branch_a = 'A'
    branch_b = 'B'

    batch_merge_job.fuse(branch_a, branch_b)

    batch_merge_job._repo.rebase.assert_called_once_with(
        branch_a,
        branch_b,
        source_repo_url=None,
    )


def test_fuse_using_merge():
    batch_merge_job = get_batch_merge_job(options=MergeJobOptions.default(use_merge_strategy=True))
    branch_a = 'A'
    branch_b = 'B'

    batch_merge_job.fuse(branch_a, branch_b)

    batch_merge_job._repo.merge.assert_called_once_with(
        branch_a,
        branch_b,
        source_repo_url=None,
    )


def test_push_batch():
    batch_merge_job = get_batch_merge_job()
    batch_merge_job.push_batch()
    batch_merge_job._repo.push.assert_called_once_with(
        BatchMergeJob.BATCH_BRANCH_NAME,
        force=True,
    )


def test_ensure_mr_not_changed():
    with patch('marge.batch_job.MergeRequest') as mr_class:
        batch_merge_job = get_batch_merge_job()
        merge_request = Mock()
        changed_merge_request = Mock()
        mr_class.fetch_by_iid.return_value = changed_merge_request

        with pytest.raises(CannotMerge):
            batch_merge_job.ensure_mr_not_changed(merge_request)

        mr_class.fetch_by_iid.assert_called_once_with(
            merge_request.project_id,
            merge_request.iid,
            batch_merge_job._api,
        )


@pytest.mark.skip('Needs API')
def test_fuse_mr_when_target_branch_was_moved():
    batch_merge_job = get_batch_merge_job()
    merge_request = Mock(target_branch='master')
    with pytest.raises(AssertionError):
        batch_merge_job.accept_mr(merge_request, 'abc')
    batch_merge_job._repo.fetch.assert_called_once_with('origin')
    batch_merge_job._repo.get_commit_hash.assert_called_once_with(
        'origin/%s' % merge_request.target_branch,
    )


@pytest.mark.skip('Needs API')
def test_fuse_mr_when_source_branch_was_moved():
    batch_merge_job = get_batch_merge_job()
    batch_merge_job._repo.reset_mock()
    merge_request = Mock(source_project_id=batch_merge_job._project.id, target_branch='master')

    sha = 'abc'
    # this will return 'abc' for both target and source branch
    # target is expected 'abc', but merge_request.sha is a mock so would not match
    batch_merge_job._repo.get_commit_hash.return_value = sha

    with pytest.raises(AssertionError):
        batch_merge_job.accept_mr(merge_request, sha)
    batch_merge_job._repo.fetch.assert_called_once_with('origin')
    batch_merge_job._repo.get_commit_hash.assert_has_calls([
        call('origin/%s' % merge_request.target_branch),
        call('origin/%s' % merge_request.source_branch),
    ])


@patch.object(BatchMergeJob, 'fuse')
@patch.object(BatchMergeJob, 'add_trailers')
@patch.object(BatchMergeJob, 'get_source_project')
@pytest.mark.skip('Needs API')
def test_fuse_mr(
    bmj_get_source_project,
    bmj_add_trailers,
    bmj_fuse,
):
    sha = 'abc'
    new_sha = 'abcd'
    batch_merge_job = get_batch_merge_job()
    batch_merge_job._repo.reset_mock()
    batch_merge_job._repo.get_commit_hash.return_value = sha
    merge_request = Mock(
        sha=sha,
        source_project_id=batch_merge_job._project.id,
        target_branch='master',
    )
    bmj_fuse.return_value = new_sha
    bmj_add_trailers.return_value = new_sha
    bmj_get_source_project.return_value = batch_merge_job._project

    r_sha = batch_merge_job.accept_mr(merge_request, sha)

    batch_merge_job._repo.fetch.assert_called_once_with('origin')
    batch_merge_job._repo.get_commit_hash.assert_has_calls([
        call('origin/%s' % merge_request.target_branch),
        call('origin/%s' % merge_request.source_branch),
    ])

    batch_merge_job._repo.checkout_branch.assert_has_calls([
        call(
            merge_request.source_branch,
            'origin/%s' % merge_request.source_branch,
        ),
        call(
            merge_request.target_branch,
            'origin/%s' % merge_request.target_branch,
        ),
    ])
    bmj_fuse.assert_has_calls([
        call(
            merge_request.source_branch,
            'origin/%s' % merge_request.target_branch,
        ),
        call(
            merge_request.target_branch,
            merge_request.source_branch,
        ),
    ])
    bmj_add_trailers.assert_called_once_with(merge_request)
    bmj_get_source_project.assert_called_once_with(merge_request)
    batch_merge_job._repo.push.assert_has_calls([
        call(
            merge_request.source_branch,
            None,
            force=True,
        ),
        call(merge_request.target_branch),
    ])
    assert r_sha == new_sha