# 서드파티 고지

이 문서는 저장소에 **포함된** 서드파티 자료와, 포함하지 않고 참조만 하는 자료를 구분해 적는다. 이 저장소 자체의 라이선스는 [LICENSE](LICENSE)(MIT)다.

## 저장소에 포함된 서드파티 자료

| 자료 | 위치 | 라이선스 | 고지 |
|---|---|---|---|
| Pretendard 폰트 `Pretendard-Bold.otf` | `assets/fonts/` | SIL Open Font License 1.1 | [`assets/fonts/LICENSE-Pretendard.txt`](assets/fonts/LICENSE-Pretendard.txt) |
| Pretendard 폰트 `Pretendard-SemiBold.otf` | `assets/fonts/` | SIL Open Font License 1.1 | [`assets/fonts/LICENSE-Pretendard.txt`](assets/fonts/LICENSE-Pretendard.txt) |

- 폰트 출처와 태그(v1.3.9), 파일 크기·SHA-256 기록은 [`assets/fonts/README.md`](assets/fonts/README.md)에 있다. 라이선스 전문과 저작권 고지는 `assets/fonts/LICENSE-Pretendard.txt`가 기준이다.
- 이 폰트는 광고 시안 이미지에 문구를 합성할 때 쓴다.

## 포함하지 않고 참조만 하는 자료

- **의존성 패키지**: 파이썬 패키지와 웹 패키지는 저장소에 포함하지 않는다. 버전은 락 파일([`uv.lock`](uv.lock), [`web/pnpm-lock.yaml`](web/pnpm-lock.yaml))을 따르고, 각 패키지의 라이선스는 해당 패키지가 배포하는 라이선스 파일을 따른다. 이 문서는 개별 패키지의 라이선스를 따로 적지 않는다.
- **웹 글꼴 패키지**: 웹 화면의 글꼴은 npm 패키지 `pretendard`(`web/package.json`의 고정 버전)를 의존성으로 설치해 쓰며 저장소에 포함하지 않는다.
- **Docker 이미지**: [`deploy/docker-compose.yml`](deploy/docker-compose.yml)은 이미지를 이름과 태그로 참조만 한다. 이미지를 저장소에 포함하거나 재배포하지 않으며, 실행할 때 사용자의 환경에서 내려받는다.
- **수집한 광고 메타데이터와 API 응답 기록**: 서드파티 콘텐츠이며 라이선스가 아니라 데이터 고지가 적용된다. [README의 데이터 고지](README.md#데이터-고지)를 따른다.
