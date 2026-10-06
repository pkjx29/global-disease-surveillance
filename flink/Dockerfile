# Flink 1.20 with the Kafka and JDBC (PostgreSQL) SQL connectors and the job definition baked in.
FROM flink:1.20.1-scala_2.12-java17

ARG MAVEN=https://repo1.maven.org/maven2
ARG KAFKA_CONNECTOR=3.3.0-1.20
ARG JDBC_CONNECTOR=3.3.0-1.20
ARG POSTGRES_DRIVER=42.7.4

RUN set -eux; cd /opt/flink/lib; \
    curl -fsSLO ${MAVEN}/org/apache/flink/flink-sql-connector-kafka/${KAFKA_CONNECTOR}/flink-sql-connector-kafka-${KAFKA_CONNECTOR}.jar; \
    curl -fsSLO ${MAVEN}/org/apache/flink/flink-connector-jdbc/${JDBC_CONNECTOR}/flink-connector-jdbc-${JDBC_CONNECTOR}.jar; \
    curl -fsSLO ${MAVEN}/org/postgresql/postgresql/${POSTGRES_DRIVER}/postgresql-${POSTGRES_DRIVER}.jar; \
    chown flink:flink /opt/flink/lib/*.jar

COPY --chown=flink:flink sql /opt/flink/job/sql
COPY --chown=flink:flink submit.sh /opt/flink/job/submit.sh
RUN chmod +x /opt/flink/job/submit.sh
