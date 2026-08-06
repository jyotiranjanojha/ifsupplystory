FROM python:3.11-slim

ARG HTTP_PROXY=http://proxy-dmz.intel.com:912
ARG HTTPS_PROXY=http://proxy-dmz.intel.com:912
ARG NO_PROXY=localhost,127.0.0.0/8,10.0.0.0/8,.intel.com

ENV http_proxy=${HTTP_PROXY} \
	https_proxy=${HTTPS_PROXY} \
	no_proxy=${NO_PROXY} \
	HTTP_PROXY=${HTTP_PROXY} \
	HTTPS_PROXY=${HTTPS_PROXY} \
	NO_PROXY=${NO_PROXY} \
	PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY webapp/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "webapp.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
