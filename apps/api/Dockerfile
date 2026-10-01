FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Huella de voz (services/voiceprint.py): WeSpeaker ResNet34 en ONNX, corre en
# la CPU del servidor. Se baja en el build y se verifica.
RUN mkdir -p /app/models \
    && curl -fsSL -o /app/models/wespeaker_en_voxceleb_resnet34.onnx \
       https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx \
    && echo "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94  /app/models/wespeaker_en_voxceleb_resnet34.onnx" \
       | sha256sum -c -

COPY . .

EXPOSE 8000
CMD ["uvicorn", "echo_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
