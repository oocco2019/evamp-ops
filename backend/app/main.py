"""
Main FastAPI application
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.core.config import settings
from app.core.database import init_db, close_db
from app.api import settings as settings_api

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting EvampOps application...")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    
    # Initialize database (in production, use Alembic migrations instead)
    if settings.DEBUG:
        logger.warning("Debug mode: Auto-creating database tables")
        await init_db()
    
    yield
    
    # Shutdown
    logger.info("Shutting down EvampOps application...")
    await close_db()


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Stock Management & Customer Service Platform",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """
    Global exception handler - never expose internal errors to clients.
    Log details server-side, return generic message to client.
    """
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred. Please try again later."
        }
    )


# Include routers
app.include_router(
    settings_api.router,
    prefix="/api/settings",
    tags=["settings"]
)

# TODO: Add more routers as they're implemented
# app.include_router(stock_api.router, prefix="/api/stock", tags=["stock"])
# app.include_router(cs_api.router, prefix="/api/customer-service", tags=["customer-service"])


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "healthy"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "database": "connected",
        "debug_mode": settings.DEBUG
    }
