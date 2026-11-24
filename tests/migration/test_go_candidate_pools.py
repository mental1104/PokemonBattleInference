"""真实PG候选池经Go/Core与原公开FastAPI逐字段差分，包含所有不可选择合法招式。"""

from __future__ import annotations

import pytest

from tests.migration.test_go_job_submission import _SubmissionClients, submission_clients


class TestOriginalCandidatePools:
    """知识合法池与Core准入组合后的公开DTO，不用测试内列表代替原仓库或工厂。"""

    @pytest.mark.parametrize("pokemon", [149,212,461,25,184,183,150])
    def test_entire_pool(self, submission_clients: _SubmissionClients, pokemon: int) -> None:
        """比较每个合法move的中文名称/类型/威力null/全部strict状态与缺失原因，不只比较支持数量。"""
        path=f"/v1/inference/candidate-pools/{pokemon}?ruleset_id=pokemon-champion&version_group_id=25"
        actual=submission_clients.remote.get(path)
        expected=submission_clients.legacy.get(path)
        (submission_clients.report / f"candidate-{pokemon}.go.json").write_bytes(actual.content)
        (submission_clients.report / f"candidate-{pokemon}.python.json").write_bytes(expected.content)
        assert actual.status_code == expected.status_code == 200, (actual.text,expected.text)
        assert actual.json() == expected.json()
        assert any(not move["admission"]["selectable"] for move in actual.json()["moves"])

    @pytest.mark.parametrize("pokemon,ruleset,version,status", [(999999,"pokemon-champion",25,404),(124,"pokemon-champion",25,404),(149,"pokemon-champion",999999,404),(149,"unknown-ruleset",25,422),(149,"pokemon-champion ",25,422)])
    def test_business_errors(self, submission_clients: _SubmissionClients,pokemon:int,ruleset:str,version:int,status:int) -> None:
        """原404/规则轴422包含业务code与message，缺知识不返回空成功池。"""
        path=f"/v1/inference/candidate-pools/{pokemon}?ruleset_id={ruleset}&version_group_id={version}"
        actual=submission_clients.remote.get(path)
        expected=submission_clients.legacy.get(path)
        assert actual.status_code == expected.status_code == status, (actual.text,expected.text)
        assert actual.json() == expected.json()

    def test_repeated_axis_uses_last_value(self,submission_clients:_SubmissionClients) -> None:
        """重复单值query沿原FastAPI取最后一项；不能把第一项未知规则/版本误当最终请求。"""
        path="/v1/inference/candidate-pools/149?ruleset_id=unknown&ruleset_id=pokemon-champion&version_group_id=1&version_group_id=25"
        actual=submission_clients.remote.get(path)
        expected=submission_clients.legacy.get(path)
        assert actual.status_code == expected.status_code == 200, (actual.text,expected.text)
        assert actual.json() == expected.json()
