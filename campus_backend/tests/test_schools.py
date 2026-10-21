"""schools 域测试：公开可访问、仅启用、含校区且按名称排序。"""

SCHOOLS_URL = "/api/schools"


def _body(res):
    return res.get_json()


class TestSchools:
    def test_public_access_without_token(self, client, db_create_all, school_fixtures):
        res = client.get(SCHOOLS_URL)
        assert res.status_code == 200
        assert _body(res)["code"] == 0

    def test_enabled_only_and_sorted_by_name(self, client, db_create_all, school_fixtures):
        data = _body(client.get(SCHOOLS_URL))["data"]
        names = [item["name"] for item in data]
        assert names == ["示例大学", "示例学院"]  # 停用学院不出现，按名称排序
        assert [item["multi_campus"] for item in data] == [True, False]

    def test_includes_enabled_campuses_sorted(self, client, db_create_all, school_fixtures):
        data = _body(client.get(SCHOOLS_URL))["data"]
        multi, single = data[0], data[1]
        assert set(multi) == {"id", "name", "multi_campus", "campuses"}
        assert [c["name"] for c in multi["campuses"]] == ["东校区", "西校区"]
        for campus in multi["campuses"]:
            assert set(campus) == {"id", "school_id", "name"}
            assert campus["school_id"] == multi["id"]
        assert [c["name"] for c in single["campuses"]] == ["主校区"]
