FROM openanolis/anolisos:8.4-x86_64

COPY INSTALLROOT /

COPY api /usr/local/lib/python3.6/site-packages/api/
RUN yum install -y python3 && \
    yum install -y gcc glibc gcc-c++ make python3-devel postgresql-devel && \
    yum clean all

RUN pip3 install supervisor uvicorn fastapi SQLAlchemy psycopg2-binary 

WORKDIR /usr/local/lib/python3.6/site-packages

CMD ["bash"]
