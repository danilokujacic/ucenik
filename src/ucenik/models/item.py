from beanie import Document


class Item(Document):
    name: str
    description: str | None = None
    price: float

    class Settings:
        name = "items"
