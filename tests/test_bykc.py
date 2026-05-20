import httpx
import pytest

from autoboya.bykc import BykcClient, parse_course
from autoboya.exceptions import CourseFull, SelectionLimitReached, SessionExpired, map_boya_error


def test_parse_course_preserves_required_fields():
    course = parse_course(
        {
            "id": 1001,
            "courseName": "美育课程",
            "coursePosition": "沙河校区 J3",
            "courseNewKind2": {"kindName": "美育"},
            "selected": False,
            "courseStartDate": "2026-05-20 10:00:00",
            "courseEndDate": "2026-05-20 11:00:00",
            "courseSelectStartDate": "2026-05-20 08:00:00",
            "courseSelectEndDate": "2026-05-20 09:00:00",
            "courseCurrentCount": 1,
            "courseMaxCount": 20,
            "courseSignConfig": '{"signPointList":[{"lat":39.981,"lng":116.344,"radius":8}]}',
        }
    )
    assert course.id == 1001
    assert course.category == "美育"
    assert course.location == "沙河校区 J3"
    assert course.sign_config["signPointList"][0]["radius"] == 8


def test_error_mapping():
    assert isinstance(map_boya_error("您的会话已失效,请重新登录后再试,谢谢!"), SessionExpired)
    assert isinstance(map_boya_error("课程容量已满"), CourseFull)
    assert isinstance(map_boya_error("已达到选课上限"), SelectionLimitReached)


def test_success_status_allows_success_message():
    payload = {"status": "0", "errmsg": "请求成功", "data": {"content": []}}

    class StaticCrypto:
        def encrypt_request(self, payload):
            from autoboya.crypto import EncryptedRequest

            return EncryptedRequest(body=b'"request"', headers={"Ak": "a", "Sk": "s", "Ts": "1"})

        def decrypt_response(self, body):
            return payload

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='"response"')

    client = BykcClient("token", http_client=httpx.Client(transport=httpx.MockTransport(handler)), use_vpn=False)
    import autoboya.bykc as bykc_module

    original = bykc_module.BykcCrypto
    bykc_module.BykcCrypto = StaticCrypto
    try:
        assert client.call("queryStudentSemesterCourseByPage", {}) == payload
    finally:
        bykc_module.BykcCrypto = original


def test_html_login_page_response_is_session_expired():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><title>CAS Login</title><form id='loginForm'></form></html>")

    client = BykcClient(
        "token",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        use_vpn=False,
    )

    with pytest.raises(SessionExpired, match="WebVPN session"):
        client.query_courses()
