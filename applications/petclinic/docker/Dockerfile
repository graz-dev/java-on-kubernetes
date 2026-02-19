ARG JAVA_VERSION=17
FROM eclipse-temurin:${JAVA_VERSION}

ARG TOMCAT_VERSION=11.0.2

RUN apt-get update -qq && apt-get install -y -qq wget && rm -rf /var/lib/apt/lists/* \
    && wget -q "https://archive.apache.org/dist/tomcat/tomcat-11/v${TOMCAT_VERSION}/bin/apache-tomcat-${TOMCAT_VERSION}.tar.gz" \
         -O /tmp/tomcat.tar.gz \
    && tar -xzf /tmp/tomcat.tar.gz -C /opt \
    && mv /opt/apache-tomcat-${TOMCAT_VERSION} /opt/tomcat \
    && rm /tmp/tomcat.tar.gz \
    && rm -rf /opt/tomcat/webapps/*

COPY spring-framework-petclinic.war /opt/tomcat/webapps/ROOT.war
COPY jvm-entrypoint.sh /jvm-entrypoint.sh
RUN chmod +x /jvm-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/jvm-entrypoint.sh"]
