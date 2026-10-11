from django.db import models


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveSmallIntegerField(default=0)
    window_start = models.DateTimeField()
