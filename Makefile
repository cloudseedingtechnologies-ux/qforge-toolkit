# Default: Python test suite. Native PMLL checks: see Makefile.pmll.
.PHONY: test check
test:
	python3 -m pytest
check: test
	$(MAKE) -f Makefile.pmll check
