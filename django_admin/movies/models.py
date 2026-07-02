import uuid

from django.db import models


class TimeStampedMixin(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDMixin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Genre(UUIDMixin, TimeStampedMixin):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'content"."genre'
        managed = False

    def __str__(self):
        return self.name


class Person(UUIDMixin, TimeStampedMixin):
    full_name = models.TextField()

    class Meta:
        db_table = 'content"."person'
        managed = False

    def __str__(self):
        return self.full_name


class FilmWork(UUIDMixin, TimeStampedMixin):
    class TypeChoices(models.TextChoices):
        MOVIE = "movie"
        TV_SHOW = "tv_show"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    creation_date = models.DateField()
    rating = models.FloatField(blank=True, null=True)
    type = models.CharField(max_length=20, choices=TypeChoices.choices)

    class Meta:
        db_table = 'content"."film_work'
        managed = False

    def __str__(self):
        return self.title
