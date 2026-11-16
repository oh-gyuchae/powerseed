from django.db import models

# 인플루언서 정보를 저장하는 데이터 모델
class Influencer(models.Model):
    name = models.CharField(max_length=100, verbose_name="인플루언서 이름")
    platform = models.CharField(max_length=50, verbose_name="SNS 플랫폼 (유튜브, 인스타 등)")
    follower_count = models.IntegerField(default=0, verbose_name="팔로워 수")
    email = models.EmailField(blank=True, null=True, verbose_name="이메일")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="등록일")

    def __str__(self):
        return self.name