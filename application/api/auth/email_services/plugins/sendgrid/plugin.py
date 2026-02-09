
class SendgridPlugin:
    def send_email(self, account, to, subject, body):
        print(f"[SENDGRID] Sending email from {account.account_id} to {to}")
        return True
