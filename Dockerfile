FROM compile:latest

COPY INSTALLROOT /
COPY requirements.txt /tmp/
RUN pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

COPY api /usr/local/python3.12/lib/python3.12/site-packages/api/
WORKDIR /usr/local/python3.12/lib/python3.12/site-packages

CMD ["supervisord", "--nodaemon"]
