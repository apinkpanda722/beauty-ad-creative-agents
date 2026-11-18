# 광고 시안 합성용 폰트

선택(조언 세션 승인, 2026-11-18): [Pretendard](https://github.com/orioncactus/pretendard),
태그 **v1.3.9**, SIL Open Font License **1.1**(OFL 1.1).
헤드라인은 `Pretendard-Bold.otf`, CTA는 `Pretendard-SemiBold.otf`를 쓴다.
원본 경로는 태그의 `packages/pretendard/dist/public/static/`이며,
라이선스 원본은 같은 태그의 루트 `LICENSE`다.

정적 OTF를 쓰는 이유는 가변 폰트 굵기 지정이 FreeType·libraqm 환경에 따라
달라질 수 있기 때문이다. 컨테이너에서도 시스템 폰트나 실행 중 네트워크 없이
같은 폰트를 쓴다. 한글 전 글리프를 담은 파일당 약 1.5 MB다(아래 표의 실제 크기).

사용자가 저장소 루트에서 실행한다:

```sh
make fetch-font
# 기존 파일을 바꾸려면
make fetch-font ARGS=--force
```

이 도구는 고정된 태그의 `raw.githubusercontent.com` 주소 세 개만 사용하며,
파일당 12 MiB 상한, 임시 파일 후 원자적 교체, 기존 파일 덮어쓰기 방지를 적용한다.
출력되는 실제 바이트 수와 SHA-256을 아래 표에 기록한다(2026-11-18 사용자가
`make fetch-font`로 내려받은 파일을 `shasum -a 256`으로 계산해 기록했다). `make verify`는 다운로드하지 않는다.
폰트가 없으면 합성을 생략하고 원본 시안을 사용한다. 실제 한글 폰트 테스트는
`font not fetched: run make fetch-font` 사유로 건너뛴다.

| 파일 | 실제 바이트 수 | SHA-256 |
|---|---|---|
| Pretendard-Bold.otf | 1,576,660 | `2e91915fab54df71cc9598ebf608b2bdb54c6fe3c066ac61dff0bc44fca71cc7` |
| Pretendard-SemiBold.otf | 1,583,704 | `c89bc43027dc7cde5726e96223376f8eec09302b2fc1f8147fd5b57cfc376118` |
| LICENSE-Pretendard.txt | 4,418 | `d31ddd9f2bed32fd7e302a205cf2380ba0de6529152d239ef99cfb6f261bfc04` |

OFL 1.1 요지: 상업 이용·수정·재배포가 가능하지만 폰트 파일을 단독 판매할 수 없다.
폰트 재배포 시 저작권 고지와 **라이선스 전문을 동봉**해야 하며,
수정본은 Reserved Font Name 제한과 OFL 유지 조건을 따라야 한다.
권리자의 이름을 허가 없이 홍보에 쓸 수 없으며 폰트는 보증 없이 제공된다.
합성 결과물 자체에 OFL을 적용할 의무는 없다. 상세 조건은 함께 받는 전문이 기준이다.

사용자가 내려받은 뒤 폰트 두 개와 `LICENSE-Pretendard.txt`를 이 디렉터리에
함께 커밋한다(무시 규칙을 추가하지 않는다). P7 컨테이너 이미지는 `assets/fonts/`를
그대로 복사하면 된다. 생성 원본·합성본은 모두 gitignore된 `data/design/`의
로컬 파일이고, 폰트와 달리 커밋하지 않는다.

## 라이선스 확인 기록

- 확인일: 2026-11-18. `LICENSE-Pretendard.txt`의 머리글은 "Copyright (c) 2021, Kil Hyung-jin
  (https://github.com/orioncactus/pretendard), with Reserved Font Name Pretendard."이고
  본문이 **SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007**이다(전문 동봉).
- 출처: `https://github.com/orioncactus/pretendard`, 태그 `v1.3.9`.
