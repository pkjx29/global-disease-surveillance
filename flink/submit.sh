#!/usr/bin/env bash
# Submit the outbreak-detection job to a running Flink session cluster.
# Connection details come from the environment so the same image works in Compose and Kubernetes.
set -euo pipefail

: "${FLINK_JOBMANAGER_HOST:=jobmanager}"
: "${KAFKA_BOOTSTRAP_SERVERS:=redpanda:9092}"
: "${KAFKA_TOPIC:=case-reports}"
: "${JDBC_URL:=jdbc:postgresql://postgres:5432/disease_surveillance}"
: "${JDBC_USER:=surveillance}"
: "${JDBC_PASSWORD:=surveillance}"
JOB_NAME="outbreak-detection"

echo "waiting for the Flink JobManager at ${FLINK_JOBMANAGER_HOST}:8081 ..."
until curl -fsS "http://${FLINK_JOBMANAGER_HOST}:8081/overview" >/dev/null; do sleep 3; done

# true when the JobManager lists our job in state RUNNING
job_running() {
  curl -fsS "http://${FLINK_JOBMANAGER_HOST}:8081/jobs/overview" \
    | grep -Eq "\"name\":\"${JOB_NAME}\"[^}]*\"state\":\"RUNNING\""
}

if job_running; then
  echo "job '${JOB_NAME}' is already running - nothing to do"
  exit 0
fi

# fill the placeholders in the SQL template
sed -e "s|\${KAFKA_BOOTSTRAP_SERVERS}|${KAFKA_BOOTSTRAP_SERVERS}|g" \
    -e "s|\${KAFKA_TOPIC}|${KAFKA_TOPIC}|g" \
    -e "s|\${JDBC_URL}|${JDBC_URL}|g" \
    -e "s|\${JDBC_USER}|${JDBC_USER}|g" \
    -e "s|\${JDBC_PASSWORD}|${JDBC_PASSWORD}|g" \
    /opt/flink/job/sql/outbreak_detection.sql > /tmp/job.sql

/opt/flink/bin/sql-client.sh \
  -Drest.address="${FLINK_JOBMANAGER_HOST}" \
  -Drest.port=8081 \
  -Dexecution.target=remote \
  -f /tmp/job.sql

# the SQL client exits 0 even when a statement fails, so confirm the job really is running
for _ in $(seq 1 20); do
  if job_running; then
    echo "job '${JOB_NAME}' is running"
    exit 0
  fi
  sleep 3
done
echo "job '${JOB_NAME}' did not reach RUNNING - see the SQL client output above" >&2
exit 1
