.PHONY: verify offline e2e logs cleanup cloud-package cloud-import-logs

verify offline:
	./verify.sh $(ARGS)

e2e:
	./verify_e2e.sh $(ARGS)

logs:
	./logs.sh $(ARGS)

cleanup:
	./cleanup.sh $(ARGS)

cloud-package:
	./cloud/build-package.sh $(ARGS)

cloud-import-logs:
	./cloud/import-logs.sh $(ARGS)
