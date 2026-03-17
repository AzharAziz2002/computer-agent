from pydantic import BaseModel, Field, model_validator


class SharedBaseModel(BaseModel):

    @model_validator(mode='before')
    def check_required_fields(cls, data):
        missing = [
            name for name, field in cls.model_fields.items()
            if field.is_required() and name not in data
        ]
        if missing:
            field_list = ", ".join(missing)
            raise ValueError(f"The following required fields are missing: {field_list}")
        return data

    class Config:
        extra = 'allow'
