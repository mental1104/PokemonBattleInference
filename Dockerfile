FROM openanolis/anolisos:8.4-x86_64

COPY INSTALLROOT /

RUN yum install -y gcc glibc gcc-c++ make wget postgresql-devel zlib-devel libffi-devel openssl-devel && \
    yum clean all

COPY Python-3.12.3.tgz /tmp/Python-3.12.3.tgz
RUN mkdir -p /usr/local/python3.12 && cd /tmp && tar xzf Python-3.12.3.tgz && \
    cd ./Python-3.12.3 && ./configure --prefix=/usr/local/python3.12 --enable-optimizations --with-lto --with-computed-gotos && \
    make -j "$(nproc)" && make altinstall && rm /tmp/Python-3.12.3.tgz && \
    /usr/local/python3.12/bin/python3.12 -m pip install --upgrade pip setuptools wheel

RUN ln -s /usr/local/python3.12/bin/python3.12        /usr/local/python3.12/bin/python3 && \
    ln -s /usr/local/python3.12/bin/python3.12        /usr/local/python3.12/bin/python && \
    ln -s /usr/local/python3.12/bin/pip3.12           /usr/local/python3.12/bin/pip3 && \
    ln -s /usr/local/python3.12/bin/pip3.12           /usr/local/python3.12/bin/pip && \
    ln -s /usr/local/python3.12/bin/pydoc3.12         /usr/local/python3.12/bin/pydoc && \
    ln -s /usr/local/python3.12/bin/idle3.12          /usr/local/python3.12/bin/idle && \
    ln -s /usr/local/python3.12/bin/python3.12-config      /usr/local/python3.12/bin/python-config

ENV PATH $PATH:/usr/local/python3.12/bin

COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

COPY api /usr/local/python3.12/lib/python3.12/site-packages/api/

WORKDIR /usr/local/python3.12/lib/python3.12/site-packages

CMD ["bash"]
