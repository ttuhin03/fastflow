{{/*
Expand the name of the chart.
*/}}
{{- define "fastflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "fastflow.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "fastflow.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "fastflow.labels" -}}
helm.sh/chart: {{ include "fastflow.chart" . }}
{{ include "fastflow.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "fastflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fastflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Orchestrator selector labels (keeps "component: api" for parity with the raw
k8s/ manifests and any existing tooling that matches on it)
*/}}
{{- define "fastflow.orchestratorSelectorLabels" -}}
{{ include "fastflow.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end -}}

{{/*
Name of the ServiceAccount to use
*/}}
{{- define "fastflow.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "fastflow.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Orchestrator image
*/}}
{{- define "fastflow.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/*
Worker image
*/}}
{{- define "fastflow.workerImage" -}}
{{- $tag := .Values.worker.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.worker.image.repository $tag -}}
{{- end -}}

{{/*
Name of the Secret holding fastflow-secrets style env vars
*/}}
{{- define "fastflow.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "fastflow.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Whether a bundled or external database is configured
*/}}
{{- define "fastflow.hasDatabase" -}}
{{- if or .Values.postgresql.enabled .Values.externalDatabaseUrl -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{/*
Name of the Secret holding DATABASE_URL / postgres credentials
*/}}
{{- define "fastflow.postgresSecretName" -}}
{{- if and .Values.postgresql.enabled .Values.postgresql.auth.existingSecret -}}
{{- .Values.postgresql.auth.existingSecret -}}
{{- else -}}
{{- printf "%s-postgres" (include "fastflow.fullname" .) -}}
{{- end -}}
{{- end -}}
