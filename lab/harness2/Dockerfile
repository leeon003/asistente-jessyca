# Dedicated lab image; never install these dependencies into JESSYCA.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --no-deps 'git+https://github.com/google-research/harness2.git@1cfe254e8d25b15f37048c3730134686abe60335'
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "-m", "harness2.cli.demo"]
CMD ["--output", "/tmp/harness2-demo", "--k", "1", "--mode", "sequential"]
