from PyQt5.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance:
    """Cegah dua instance. Aman terhadap proses yang di-kill (socket mati bersama prosesnya)."""

    def __init__(self, name="gtd_value_overlay"):
        self.name = name
        self.server = None

    def already_running(self):
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if sock.waitForConnected(300):                 # ada instance lain yang benar-benar hidup
            sock.disconnectFromServer()
            return True
        QLocalServer.removeServer(self.name)           # buang sisa socket dari proses yang di-kill
        self.server = QLocalServer()
        return not self.server.listen(self.name)       # gagal listen = instance lain menang balapan