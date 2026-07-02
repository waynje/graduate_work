from django.contrib import admin

from movies.models import FilmWork, Genre, Person


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name", "id")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name",)
    search_fields = ("full_name", "id")


@admin.register(FilmWork)
class FilmWorkAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "creation_date", "rating")
    list_filter = ("type", "creation_date")
    search_fields = ("title", "description", "id")
