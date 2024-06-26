from fastapi import FastAPI, HTTPException, status, Depends, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, constr, validator
from sqlalchemy import create_engine, MetaData, select, Table, Column, Integer, String, ForeignKey, Boolean, DateTime
from passlib.context import CryptContext
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from typing import List, Optional
from datetime import timezone
import jwt
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from fastapi_session import Session
import secrets
from datetime import datetime
from sqlalchemy.orm import joinedload
from fastapi.responses import RedirectResponse
from starlette.config import Config
from urllib.parse import urlencode
import httpx
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from sqlalchemy.exc import IntegrityError
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import re
from starlette.middleware.sessions import SessionMiddleware
import os
from fastapi import Path

load_dotenv()

app = FastAPI()

SECRET_KEY = "d38b291ccebc18af95d4df97a0a98f9bb9eea3c820e771096fa1c5e3a58f3d53"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

app.add_middleware(SessionMiddleware, secret_key="8c87d814d4be0ddc08364247da359a61941957e84f62f3cd0e87eb5d853a4144")


DATABASE_URL = "mssql+pyodbc://db_aa8202_tourism_admin:ABCD1234@SQL5113.site4now.net/db_aa8202_tourism?driver=ODBC+Driver+17+for+SQL+Server"
engine = create_engine(DATABASE_URL)
metadata = MetaData()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

users = Table(
    "users",
    metadata,
    Column("user_id", Integer, primary_key=True, index=True),
    Column("first_name", String(length=255)),
    Column("last_name", String(length=255)),
    Column("user_email", String),
    Column("user_password", String),
    Column("user_location", String),
)

metadata.create_all(bind=engine)


def query_database(country: str, governorate: str, category: str, name: str) -> List[str]:
    return []


class UserRegistration(BaseModel):
    first_name: constr(min_length=3, max_length=16)
    last_name: constr(min_length=3, max_length=16)
    user_password: constr(min_length=8,max_length=64)
    user_email: EmailStr
    user_location: Optional[str] = None
    @classmethod
    def validate_email_domain(cls, email: str):
        allowed_domains = ["yahoo.com", "gmail.com", "mail.com", "outlook.com", "hotmail.com"]
        email_domain = email.split('@')[1]
        if email_domain not in allowed_domains:
            raise ValueError("Only Yahoo, Gmail, Mail, Outlook, and Hotmail domains are allowed")

    @validator("user_email")
    def validate_email(cls, v):
        cls.validate_email_domain(v)
        return v

    @validator("user_password")
    def validate_password(cls, v):
        errors = []
        if len(v) < 8 or len(v) > 64:
            errors.append("Password must be between 8 and 64 characters long")
        if not re.search(r'[A-Z]', v):
            errors.append("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', v):
            errors.append("Password must contain at least one lowercase letter")
        if not re.search(r'\d', v):
            errors.append("Password must contain at least one number")
        if not re.search(r'[@$!%*?&]', v):
            errors.append("Password must contain at least one special character (@$!%*?&)")
        if errors:
            raise ValueError(", ".join(errors))
        return v

class UserLogin(BaseModel):
    user_email: EmailStr
    user_password: str


class UserUpdate(BaseModel):
    first_name: str
    last_name: str
    user_location: str




oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return password_context.hash(password)


def verify_user_credentials(user_email: str, user_password: str):
    conn = engine.connect()
    query = select(users.c.user_email, users.c.user_password).where(users.c.user_email == user_email)
    result = conn.execute(query).fetchone()

    if result and password_context.verify(user_password, result[1]):
        return True
    return False

def register_user(user: UserRegistration):
    if not re.match("^(?=.*[a-zA-Z])[a-zA-Z0-9]*$", user.first_name):
        raise HTTPException(status_code=400, detail="First name must contain at least one letter")

    if not re.match("^(?=.*[a-zA-Z])[a-zA-Z0-9]*$", user.last_name):
        raise HTTPException(status_code=400, detail="Last name must contain at least one letter")
    conn = engine.connect()
    try:
        conn.execute(users.insert().values(
            first_name=user.first_name,
            last_name=user.last_name,
            user_password=hash_password(user.user_password),
            user_email=user.user_email,
            user_location=user.user_location,
        ))
        conn.commit()
    except IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="User with this email already registered")
    finally:
        conn.close()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    for error in errors:
        if error['loc'][-1] == 'first_name':
            return JSONResponse(
                status_code=400,
                content={"message": "First name length must be between 3 and 16 characters"}
            )
        if error['loc'][-1] == 'last_name':
            return JSONResponse(
                status_code=400,
                content={"message": "Last name length must be between 3 and 16 characters"}
            )

        if error['loc'][-1] == 'user_email':
            return JSONResponse(
                status_code=400,
                content={"message": "Only Yahoo, Gmail, Mail, Outlook, and Hotmail domains are allowed"}
            )
        if error['loc'][-1] == 'user_password':
            return JSONResponse(
                status_code=400,
                content={"message": error['msg']}
            )
    return JSONResponse(
        status_code=400,
        content={"message": "Invalid input"}
    )

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


def delete_user(user_email: str):
    conn = engine.connect()
    try:
        conn.execute(users.delete().where(users.c.user_email == user_email))
        conn.commit()
    except SQLAlchemyError as e:
        conn.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user")
    finally:
        conn.close()


def update_user(user_email: str, updated_user: UserUpdate):
    if not re.match("^(?=.*[a-zA-Z])[a-zA-Z0-9]*$", updated_user.first_name):
        raise HTTPException(status_code=400, detail="First name must contain at least one letter")

    if not re.match("^(?=.*[a-zA-Z])[a-zA-Z0-9]*$", updated_user.last_name):
        raise HTTPException(status_code=400, detail="Last name must contain at least one letter")

    if len(updated_user.first_name) < 3 or len(updated_user.first_name) > 16:
        raise HTTPException(status_code=400, detail="First name length must be between 3 and 16 characters")

    if len(updated_user.last_name) < 3 or len(updated_user.last_name) > 16:
        raise HTTPException(status_code=400, detail="Last name length must be between 3 and 16 characters")

    conn = engine.connect()
    conn.execute(users.update().where(users.c.user_email == user_email).values(
        first_name=updated_user.first_name.capitalize(),
        last_name=updated_user.last_name.capitalize(),
        user_location=updated_user.user_location,
    ))
    conn.commit()
    conn.close()



UTC = timezone.utc
def create_access_token(data: dict):
    encoded_jwt = jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email = payload.get("sub")
        if user_email is None:
            return None
        return user_email
    except jwt.JWTError:
        return None

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email = payload.get("sub")
        if user_email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_email
    except jwt.JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@app.post("/register")
async def register(user: UserRegistration):
    conn = engine.connect()
    query = select(users.c.user_email).where(users.c.user_email == user.user_email)
    result = conn.execute(query).fetchone()
    conn.close()

    if result:
        raise HTTPException(status_code=400, detail="User with this email already registered")

    first_name = user.first_name.capitalize()
    last_name = user.last_name.capitalize()

    if len(first_name) < 3 or len(first_name) > 16:
        raise HTTPException(status_code=400, detail="First name length must be between 3 and 16 characters")

    if len(last_name) < 3 or len(last_name) > 16:
        raise HTTPException(status_code=400, detail="Last name length must be between 3 and 16 characters")

    register_user(UserRegistration(
        first_name=first_name,
        last_name=last_name,
        user_password=user.user_password,
        user_email=user.user_email,
        user_location=user.user_location,
    ))

    return {"message": "Registration successful"}

@app.post("/login")
async def login(user: UserLogin):
    user_email = user.user_email
    user_password = user.user_password

    if not verify_user_credentials(user_email, user_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password. please try again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user_email})
    return {"access_token": access_token, "token_type": "bearer", "message": "Login successful"}


@app.delete("/delete")
async def delete(current_user: str = Depends(get_current_user)):
    delete_user(current_user)
    return {"message": "User deleted successfully"}


@app.put("/update")
async def update(updated_user: UserUpdate, current_user: str = Depends(get_current_user)):
    update_user(current_user, updated_user)
    return {"message": "User updated successfully"}



@app.put("/reset_password")
async def reset_password(user_email: str, new_password: str):
    if not re.match(r"[^@]+@[^@]+\.[^@]+", user_email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    email_domain = user_email.split('@')[1]

    allowed_domains = ["yahoo.com", "gmail.com", "mail.com", "outlook.com", "hotmail.com"]
    if email_domain not in allowed_domains:
        raise HTTPException(status_code=400, detail="Only Yahoo, Gmail, Mail, Outlook, and Hotmail domains are allowed")

    conn = engine.connect()
    query = select(users.c.user_email).where(users.c.user_email == user_email)
    result = conn.execute(query).fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    errors = []
    if len(new_password) < 8 or len(new_password) > 64:
        errors.append("Password must be between 8 and 64 characters long")
    if not re.search(r'[A-Z]', new_password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', new_password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r'\d', new_password):
        errors.append("Password must contain at least one number")
    if not re.search(r'[@$!%*?&]', new_password):
        errors.append("Password must contain at least one special character (@$!%*?&)")
    if errors:
        raise HTTPException(status_code=400, detail=", ".join(errors))

    # Hash the new password
    hashed_password = hash_password(new_password)


    conn = engine.connect()
    conn.execute(users.update().where(users.c.user_email == user_email).values(
        user_password=hashed_password
    ))
    conn.close()

    return {"message": "Password reset successful"}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

recent_searches = []

class RecentSearch(Base):
    __tablename__ = 'recent_searches'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    country = Column(String)
    governorate = Column(String)
    category = Column(String)
    name = Column(String)


class SearchParams(BaseModel):
    country: Optional[str] = "string"
    governorate: Optional[str] = "string"
    category: Optional[str] = "string"
    name: Optional[str] = "string"


from sqlalchemy import or_


@app.post("/search")
async def search(
        search_params: SearchParams,
        current_user: str = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    try:
        user = db.query(User).filter(User.user_email == current_user).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        recent_search = RecentSearch(
            user_id=user.user_id,
            country=search_params.country,
            governorate=search_params.governorate,
            category=search_params.category,
            name=search_params.name
        )
        db.add(recent_search)
        db.commit()

        recent_searches = db.query(RecentSearch).filter(RecentSearch.user_id == user.user_id).order_by(
            RecentSearch.id.desc()).all()

        if len(recent_searches) > 10:
            oldest_searches_to_delete = recent_searches[10:]
            for search_to_delete in oldest_searches_to_delete:
                db.delete(search_to_delete)
            db.commit()

        # Search in all three tables for matching results
        search_results = db.query(Hotel).filter(
            or_(
                Hotel.hotel_loc.ilike(f"%{search_params.name}%"),
                Hotel.hotel_name.ilike(f"%{search_params.name}%")
            )
        ).all()
        search_results += db.query(Place).filter(
            or_(
                Place.place_loc.ilike(f"%{search_params.name}%"),
                Place.place_name.ilike(f"%{search_params.name}%")
            )
        ).all()
        search_results += db.query(Restaurant).filter(
            or_(
                Restaurant.rest_loc.ilike(f"%{search_params.name}%"),
                Restaurant.rest_name.ilike(f"%{search_params.name}%")
            )
        ).all()

        if not search_results:
            return {"message": "No matching results found."}

        # Transforming the results into dictionaries
        results = []
        for item in search_results:
            if isinstance(item, Hotel):
                results.append({
                    "type": "hotel",
                    "name": item.hotel_name,
                    "price": item.price,
                    "governorate": item.governorate,
                    "country": item.hotel_loc,
                    "image": item.hotel_image,
                    "rate": item.rate

                })
            elif isinstance(item, Place):
                results.append({
                    "type": "place",
                    "name": item.place_name,
                    "price": item.price,
                    "governorate": item.governorate,
                    "country": item.place_loc,
                    "image": item.place_image,
                    "rate": item.rate
                })
            elif isinstance(item, Restaurant):
                results.append({
                    "type": "restaurant",
                    "name": item.rest_name,
                    "price": item.price,
                    "governorate": item.governorate,
                    "country": item.rest_loc,
                    "image": item.rest_image,
                    "rate": item.rate

                })

        return {"results": results}
    except SQLAlchemyError as e:
        db.rollback()
        return {"message": f"Database error: {str(e)}"}
    finally:
        db.close()


@app.get("/recent_searches")
async def get_recent_searches(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_email == current_user).first()
    if user:
        recent_searches = db.query(RecentSearch).filter(RecentSearch.user_id == user.user_id).order_by(RecentSearch.id.desc()).limit(10).all()
        return {"recent_searches": recent_searches}
    else:
        return {"message": "User not found."}


@app.put("/change_password")
async def change_password(current_password: str, new_password: str, current_user: str = Depends(get_current_user)):
    conn = engine.connect()
    query = select(users.c.user_password).where(users.c.user_email == current_user)
    result = conn.execute(query).fetchone()
    if not result or not password_context.verify(current_password, result[0]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if current_password == new_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current password")

    errors = []
    if len(new_password) < 8 or len(new_password) > 64:
        errors.append("Password must be between 8 and 64 characters long")
    if not re.search(r'[A-Z]', new_password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', new_password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r'\d', new_password):
        errors.append("Password must contain at least one number")
    if not re.search(r'[@$!%*?&]', new_password):
        errors.append("Password must contain at least one special character (@$!%*?&)")
    if errors:
        raise HTTPException(status_code=400, detail=", ".join(errors))

    hashed_new_password = hash_password(new_password)
    conn.execute(users.update().where(users.c.user_email == current_user).values(user_password=hashed_new_password))
    conn.commit()
    conn.close()
    return {"message": "Password changed successfully"}





def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

config = Config(".env")
GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "http://smart-tourism-mjyq.onrender.com/auth/google/callback"

GMAIL_USER = config("GMAIL_USER")
GMAIL_PASSWORD = config("GMAIL_PASSWORD")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def send_email(subject, message, recipient):
    try:
        msg = MIMEMultipart()
        msg['From'] = formataddr(("Smart Tourism", GMAIL_USER))
        msg['To'] = recipient
        msg['Subject'] = subject

        message_lines = message.split("\n")
        body = "\n".join(message_lines) + "\nWelcome to Smart Tourism Family!"
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(GMAIL_USER, recipient, text)
        server.quit()
        print('Email sent successfully')
    except Exception as e:
        print('Failed to send email:', str(e))


@app.get("/auth/google")
def auth_google():
    google_auth_endpoint = "https://accounts.google.com/o/oauth2/auth"
    query_params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": REDIRECT_URI,
        "access_type": "offline",
        "prompt": "consent",
        "state": "send_welcome_email"
    }

    return RedirectResponse(url=f"{google_auth_endpoint}?{urlencode(query_params)}")

@app.get("/auth/google/callback")
async def auth_google_callback(request: Request, background_tasks: BackgroundTasks):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not found")

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        token_response = await client.post(token_url, data=token_data)
        token_json = token_response.json()

    if "error" in token_json:
        raise HTTPException(status_code=400, detail=token_json["error"])

    access_token = token_json.get("access_token")

    # Use the access token to get user info from Google
    user_info_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        user_info_response = await client.get(user_info_url, headers=headers)
        user_info = user_info_response.json()

    user_email = user_info.get("email")
    first_name = user_info.get("given_name", "DefaultFirstName")
    last_name = user_info.get("family_name", "DefaultLastName")

    if not user_email:
        raise HTTPException(status_code=400, detail="Failed to retrieve necessary user information from Google")

    conn = engine.connect()
    query = select(users.c.user_email).where(users.c.user_email == user_email)
    result = conn.execute(query).fetchone()

    if not result:
        user = UserRegistration(
            first_name=first_name,
            last_name=last_name,
            user_password=secrets.token_urlsafe(16),  # Generate a random password
            user_email=user_email,
            user_location=None,
        )
        register_user(user)
        background_tasks.add_task(send_email, "Welcome to Our Application!",
                                  "Thank you for joining our application. We're excited to have you on board!",
                                  user_email)

    access_token = create_access_token(data={"sub": user_email})

    return {"access_token": access_token, "token_type": "bearer", "message": "Login successful"}

@app.post("/logout")
async def logout(current_user: str = Depends(get_current_user)):
    """
ليه ياعم تخرج ما انت منورنا والله!!!!!
    """
    return {"message": "Logout successful"}

class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    user_email = Column(String(255), nullable=False)
    user_password = Column(String(255), nullable=False)
    user_location = Column(String(255))
    user_favs = relationship("UserFavorite", back_populates="user")
    plans = relationship("UserPlan", back_populates="user")


class Plan(Base):
    __tablename__ = 'plans'
    plan_id = Column(Integer, primary_key=True)
    plan_budget = Column(Integer, nullable=False)
    plan_review = Column(String(255))
    plan_duration = Column(Integer, nullable=False)
    destination = Column(String(50), nullable=False)
    plan_is_recommended = Column(Boolean, nullable=False)

    users = relationship("UserPlan", back_populates="plan")



class Place(Base):
    __tablename__ = 'places'
    place_id = Column(Integer, primary_key=True)
    place_name = Column(String(255), nullable=False)
    price = Column(Integer, nullable=False)
    governorate = Column(String(255), nullable=False)
    place_loc = Column(String(255), nullable=False)
    place_image = Column(String(255), nullable=False)
    rate = Column(Integer)

class Hotel(Base):
    __tablename__ = 'hotels'
    hotel_id = Column(Integer, primary_key=True)
    hotel_name = Column(String(255), nullable=False)
    price = Column(Integer, nullable=False)
    governorate = Column(String(255), nullable=False)
    hotel_loc = Column(String(255), nullable=False)
    hotel_image = Column(String(255), nullable=False)
    rate = Column(Integer)

class Restaurant(Base):
    __tablename__ = 'restaurants'
    rest_id = Column(Integer, primary_key=True)
    rest_name = Column(String(255), nullable=False)
    price = Column(Integer, nullable=False)
    governorate = Column(String(255), nullable=False)
    rest_loc = Column(String(255), nullable=False)
    rest_image = Column(String(255), nullable=False)
    rate = Column(Integer)

class UserPlan(Base):
    __tablename__ = 'user_plan'
    history_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    plan_id = Column(Integer, ForeignKey('plans.plan_id'))
    timestamp = Column(DateTime, nullable=False, default=datetime.now())
    user = relationship("User", back_populates="plans")
    plan = relationship("Plan", back_populates="users")

# Define association tables
plan_place = Table('plan_place', Base.metadata,
    Column('plan_id', Integer, ForeignKey('plans.plan_id')),
    Column('place_id', Integer, ForeignKey('places.place_id'))
)

plan_hotel = Table('plan_hotel', Base.metadata,
    Column('plan_id', Integer, ForeignKey('plans.plan_id')),
    Column('hotel_id', Integer, ForeignKey('hotels.hotel_id'))
)

plan_restaurant = Table('plan_restaurant', Base.metadata,
    Column('plan_id', Integer, ForeignKey('plans.plan_id')),
    Column('rest_id', Integer, ForeignKey('restaurants.rest_id'))
)

class PlanCreate(BaseModel):
    plan_budget: int
    plan_review: str = None
    plan_duration: int
    destination: str
    plan_is_recommended: bool
    restaurant_names: List[str] = []
    hotel_names: List[str] = []
    place_names: List[str] = []

class Favorite(Base):
        __tablename__ = "favorites"
        fav_id = Column(Integer, primary_key=True, index=True)
        type = Column(String, nullable=False)
        name = Column(String, nullable=False)
        location = Column(String)
        user_favs = relationship("UserFavorite", back_populates="favorite")

class UserFavorite(Base):
        __tablename__ = "user_fav"
        user_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
        fav_id = Column(Integer, ForeignKey("favorites.fav_id"), primary_key=True)
        user = relationship("User", back_populates="user_favs")
        favorite = relationship("Favorite", back_populates="user_favs")

Base.metadata.create_all(bind=engine)

def create_favorite(db: Session, user_id: int, type: str, name: str, location: str):
        db_favorite = Favorite(type=type, name=name, location=location)
        db.add(db_favorite)
        db.commit()
        db.refresh(db_favorite)
        return db_favorite

def delete_favorite(db: Session, name: str):
    db_favorite = db.query(Favorite).filter(Favorite.name == name).first()
    if db_favorite:
        db.delete(db_favorite)
        db.commit()
        return {"message": "Favorite deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Favorite not found")

# Database session setup
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/create_plan")
async def create_plan(
        plan_data: PlanCreate,
        current_user: str = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Create a plan for the current user.
    """
    try:
        user = db.query(User).filter(User.user_email == current_user).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Check if the destination exists
        destination = plan_data.destination
        country_exists = db.query(Place).filter(Place.place_loc.ilike(f"%{destination}%")).first()
        if not country_exists:
            raise HTTPException(status_code=404, detail=f"Country '{destination}' not found in the database")

        # Check if all specified places, hotels, and restaurants exist in the destination
        places_not_found = []
        for place_name in plan_data.place_names:
            place = db.query(Place).filter(Place.place_name == place_name,
                                           Place.place_loc.ilike(f"%{destination}%")).first()
            if not place:
                places_not_found.append(place_name)

        hotels_not_found = []
        for hotel_name in plan_data.hotel_names:
            hotel = db.query(Hotel).filter(Hotel.hotel_name == hotel_name,
                                           Hotel.hotel_loc.ilike(f"%{destination}%")).first()
            if not hotel:
                hotels_not_found.append(hotel_name)

        restaurants_not_found = []
        for rest_name in plan_data.restaurant_names:
            restaurant = db.query(Restaurant).filter(Restaurant.rest_name == rest_name,
                                                     Restaurant.rest_loc.ilike(f"%{destination}%")).first()
            if not restaurant:
                restaurants_not_found.append(rest_name)

        if places_not_found or hotels_not_found or restaurants_not_found:
            not_found_message = ""
            if places_not_found:
                not_found_message += f"Places not found: {', '.join(places_not_found)}. "
            if hotels_not_found:
                not_found_message += f"Hotels not found: {', '.join(hotels_not_found)}. "
            if restaurants_not_found:
                not_found_message += f"Restaurants not found: {', '.join(restaurants_not_found)}. "

            return {"message": "Plan not created", "missing_entries": not_found_message}

        # Create Plan instance
        plan = Plan(
            plan_budget=plan_data.plan_budget,
            plan_review=plan_data.plan_review,
            plan_duration=plan_data.plan_duration,
            destination=destination,
            plan_is_recommended=plan_data.plan_is_recommended
        )
        db.add(plan)
        db.flush()

        user_plan = UserPlan(user_id=user.user_id, plan_id=plan.plan_id)
        db.add(user_plan)

        for place_name in plan_data.place_names:
            place = db.query(Place).filter(Place.place_name == place_name,
                                           Place.place_loc.ilike(f"%{destination}%")).first()
            db.execute(plan_place.insert().values(plan_id=plan.plan_id, place_id=place.place_id))

        for hotel_name in plan_data.hotel_names:
            hotel = db.query(Hotel).filter(Hotel.hotel_name == hotel_name,
                                           Hotel.hotel_loc.ilike(f"%{destination}%")).first()
            db.execute(plan_hotel.insert().values(plan_id=plan.plan_id, hotel_id=hotel.hotel_id))

        for rest_name in plan_data.restaurant_names:
            restaurant = db.query(Restaurant).filter(Restaurant.rest_name == rest_name,
                                                     Restaurant.rest_loc.ilike(f"%{destination}%")).first()
            db.execute(plan_restaurant.insert().values(plan_id=plan.plan_id, rest_id=restaurant.rest_id))

        db.commit()

        return {"message": "Plan created successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create plan: {e}")
    finally:
        db.close()


class SavedPlanResponse(BaseModel):
    plan_budget: int
    plan_review: Optional[str]
    plan_duration: int
    destination: str
    plan_is_recommended: bool
    places: List[str] = []
    hotels: List[str] = []
    restaurants: List[str] = []


@app.get("/history plans")
async def get_saved_plans(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.user_email == current_user).first()
        if user:
            user_plans = db.query(UserPlan).join(Plan).options(joinedload(UserPlan.plan)).filter(UserPlan.user_id == user.user_id).all()

            saved_plans_response = []
            for user_plan in user_plans:
                saved_plan = SavedPlanResponse(
                    plan_budget=user_plan.plan.plan_budget,
                    plan_review=user_plan.plan.plan_review,
                    plan_duration=user_plan.plan.plan_duration,
                    destination=user_plan.plan.destination,
                    plan_is_recommended=user_plan.plan.plan_is_recommended
                )


                places = db.query(Place.place_name).join(plan_place).filter(plan_place.c.plan_id == user_plan.plan_id).all()
                saved_plan.places = [place[0] for place in places]


                hotels = db.query(Hotel.hotel_name).join(plan_hotel).filter(plan_hotel.c.plan_id == user_plan.plan_id).all()
                saved_plan.hotels = [hotel[0] for hotel in hotels]


                restaurants = db.query(Restaurant.rest_name).join(plan_restaurant).filter(plan_restaurant.c.plan_id == user_plan.plan_id).all()
                saved_plan.restaurants = [restaurant[0] for restaurant in restaurants]

                saved_plans_response.append(saved_plan)

            return {"user_plans": saved_plans_response}
        else:
            return {"message": "User not found."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch user plans: {e}")
    finally:
        db.close()


class FavoriteCreate(BaseModel):
    type: str
    name: str
    location: str
@app.post("/favorites/")
def create_favorite_endpoint(
    favorite_data: FavoriteCreate,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a favorite for the current user.
    """
    try:
        user = db.query(User).filter(User.user_email == current_user_email).first()
        if user:
            favorite = create_favorite(
                db=db,
                user_id=user.user_id,
                **favorite_data.dict()
            )
            return favorite
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create favorite: {e}")


@app.delete("/favorites/{name}")
def delete_favorite_endpoint(
    name: str = Path(..., title="Name of the favorite place"),
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a favorite for the current user using the favorite name.
    """
    try:
        user = db.query(User).filter(User.user_email == current_user_email).first()
        if user:
            result = delete_favorite(db=db, name=name)
            return result
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete favorite: {e}")



# -------------------------------------------------------------------------
class SurveyResponse(BaseModel):
    category: str

# SQLAlchemy models
class Survey(Base):
    __tablename__ = "surveys"
    survey_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)

class Option(Base):
    __tablename__ = "options"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.survey_id"))

@app.post("/survey/")
async def survey(survey_response: SurveyResponse, current_user_email: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_email == current_user_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        survey = Survey(user_id=user.user_id)  # Using the current user's ID obtained from the database
        db.add(survey)
        db.commit()
        db.refresh(survey)

        # Create option entry
        option = Option(category=survey_response.category, survey_id=survey.survey_id)
        db.add(option)
        db.commit()
        db.refresh(option)

        return {"message": "Survey submitted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    finally:
        db.close()

@app.get("/out-put survey")
async def get_user_survey(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.user_email == current_user).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        survey = db.query(Survey).filter(Survey.user_id == user.user_id).order_by(Survey.survey_id.desc()).first()

        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found for the current user")

        options = db.query(Option).filter(Option.survey_id == survey.survey_id).all()

        categories = [option.category for option in options]

        return {"categories": categories}
    except SQLAlchemyError as e:
        return {"message": f"Database error: {str(e)}"}




@app.get("/protected")
async def protected_endpoint(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.user_email == current_user).first()
        if user:
            return {
                "message": f"Hello, {user.first_name} {user.last_name}. You are authenticated.",
                "user_info": {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.user_email,
                    "location": user.user_location
                }
            }
        else:
            return {"message": "User not found."}
    except SQLAlchemyError as e:
        return {"message": f"Database error: {str(e)}"}

@app.get("/unprotected")
async def unprotected_endpoint():

    return {"message": "This endpoint is accessible without authentication."}


#--------------------------------------------------------
from sqlalchemy.sql import func
def query_random_places(db: Session, country: str):
    random_places = db.query(
        Place.place_name,
        Place.price,
        Place.governorate,
        Place.place_loc,
        Place.place_image,
        Place.rate
    ).filter(
        Place.place_loc.ilike(f"%{country}%")
    ).order_by(
        func.newid()
    ).limit(5).all()
    return random_places
def query_random_restaurants(db: Session, country: str):
    random_restaurants = db.query(
        Restaurant.rest_name,
        Restaurant.price,
        Restaurant.governorate,
        Restaurant.rest_loc,
        Restaurant.rest_image,
        Restaurant.rate
    ).filter(
        Restaurant.rest_loc.ilike(f"%{country}%")
    ).order_by(
        func.newid()
    ).limit(5).all()
    return random_restaurants
def query_random_hotels(db: Session, country: str):
    random_hotels = db.query(
        Hotel.hotel_name,
        Hotel.price,
        Hotel.governorate,
        Hotel.hotel_loc,
        Hotel.hotel_image,
        Hotel.rate

    ).filter(
        Hotel.hotel_loc.ilike(f"%{country}%")
    ).order_by(
        func.newid()
    ).limit(5).all()
    return random_hotels

@app.get("/discover_places/")
async def get_discover_places(country: str, db: Session = Depends(get_db)):
    random_places = query_random_places(db, country)
    if not random_places:
        raise HTTPException(status_code=404, detail="No random places found for the specified country")

    result = [
        {
            "place_name": place[0],
            "price": place[1],
            "governorate": place[2],
            "place_loc": place[3],
            "place_image": place[4],
            "rate": place[5]
        } for place in random_places
    ]

    return {"random_places": result}

@app.get("/discover_restaurants/")
async def get_discover_restaurants(country: str, db: Session = Depends(get_db)):
    random_restaurants = query_random_restaurants(db, country)
    if not random_restaurants:
        raise HTTPException(status_code=404, detail="No random restaurants found for the specified country")

    result = [
        {
            "rest_name": restaurant[0],
            "price": restaurant[1],
            "governorate": restaurant[2],
            "rest_loc": restaurant[3],
            "rest_image": restaurant[4],
            "rate": restaurant[5]
        } for restaurant in random_restaurants
    ]

    return {"random_restaurants": result}
@app.get("/discover_hotels/")
async def get_discover_hotels(country: str, db: Session = Depends(get_db)):
    random_hotels = query_random_hotels(db, country)
    if not random_hotels:
        raise HTTPException(status_code=404, detail="No random hotels found for the specified country")

    result = [
        {
            "hotel_name": hotel[0],
            "price": hotel[1],
            "governorate": hotel[2],
            "hotel_loc": hotel[3],
            "hotel_image": hotel[4],
            "rate": hotel[5]

        } for hotel in random_hotels
    ]

    return {"random_hotels": result}

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
if __name__ == "__main__":
    main()
