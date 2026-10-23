# 판례집 — 데이터 갱신·빌드·검사 (python3 필요; 선택 패키지는 requirements.txt)
PY ?= python3
TPL := src/design-d.html
OUT := output/casebook.html

.PHONY: all data laws build web webcheck check fetch validate shots clean

all: data build check

data:            ## registry.json + toc.json + fetched/ → data/cases.json
	$(PY) tools/build_data.py

laws:            ## data/laws_md/*.md → data/laws.json
	$(PY) tools/build_laws.py data/laws_md

build:           ## cases.json + laws.json → output/casebook.html
	$(PY) tools/build.py $(TPL) $(OUT)

web:             ## versioned data + installable web app -> output/web/
	$(PY) tools/build_web.py

webcheck:        ## HTTP paths, lazy text and offline QA
	$(PY) tools/test_web.py

check:           ## 45+건 × 4탭 × 2뷰포트 오류·가로스크롤 검사 + 법령 페이지 + 법률신문 연도·필터·찾기 동작
	$(PY) tools/sweep.py $(OUT)

fetch:           ## registry 에 있지만 수집되지 않은 사건의 공식 텍스트를 law.go.kr 에서 수집 (사용자 PC에서)
	$(PY) tools/fetch_lawgo.py --all-missing

validate:        ## 등록부·목차 정합성 점검
	$(PY) tools/add_cases.py validate

shots:           ## 대표 화면 스크린샷 (shots/)
	$(PY) tools/shot.py $(OUT) shots/final

clean:
	rm -rf output/*.html shots/*.png
