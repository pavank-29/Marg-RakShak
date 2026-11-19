"""HDBSCAN Spatial Hotspot Clustering Engine.
Discovers high-density accident clusters from raw incident coordinates using spherical Haversine metric.
Distinguishes KNOWN_BLACKSPOT (official traffic authority records) from ML_DISCOVERED_HOTSPOT.
"""
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import joblib
import numpy as np
from sqlalchemy.orm import Session
from sklearn.cluster import HDBSCAN

from app.core.config import settings
from app.ml.feature_engineering import haversine_distance
from app.ml.schemas import ClusteringResponse, ClusterItem

logger = logging.getLogger(__name__)

EARTH_RADIUS_METERS = 6371000.0


class HotspotClusterer:
    """HDBSCAN-based geospatial accident cluster detector."""

    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = Path(model_dir or settings.MODEL_DIR) / "hdbscan_model"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.model_dir / "hdbscan_clusterer.joblib"
        self.last_clusterer: Optional[HDBSCAN] = None
        self.last_metadata: Dict[str, Any] = {}

    def cluster_accidents(
        self,
        accident_records: List[Dict[str, Any]],
        min_cluster_size: int = 3,
        min_samples: int = 2,
    ) -> Tuple[List[ClusterItem], int, int]:
        """Perform HDBSCAN clustering on geographic coordinates of accident incidents.
        
        Args:
            accident_records: List of dicts with 'latitude', 'longitude', optional 'fatalities', 'injuries', 'severity'
            min_cluster_size: Minimum number of incidents to form a cluster
            min_samples: HDBSCAN core distance sensitivity
            
        Returns:
            Tuple of (clusters_list, discovered_clusters_count, noise_points_count)
        """
        if not accident_records or len(accident_records) < min_cluster_size:
            logger.info(
                f"Insufficient incident records ({len(accident_records)}). "
                f"HDBSCAN requires at least {min_cluster_size} records."
            )
            return [], 0, len(accident_records)

        # Validate and extract coordinates
        valid_records = []
        coords_deg = []
        for r in accident_records:
            try:
                lat = float(r.get("latitude") if r.get("latitude") is not None else r.get("lat"))
                lng = float(r.get("longitude") if r.get("longitude") is not None else r.get("lng"))
            except (TypeError, ValueError):
                continue

            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                valid_records.append(r)
                coords_deg.append([lat, lng])

        if len(valid_records) < min_cluster_size:
            return [], 0, len(valid_records)

        coords_array = np.array(coords_deg, dtype=np.float64)
        # Convert lat/lng to radians for spherical Haversine distance
        coords_rad = np.radians(coords_array)

        # Execute HDBSCAN clustering with Haversine metric
        clusterer = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="haversine",
            cluster_selection_method="eom",
            allow_single_cluster=True,
            copy=True
        )
        labels = clusterer.fit_predict(coords_rad)
        self.last_clusterer = clusterer

        # Save fitted clusterer
        try:
            joblib.dump(clusterer, self.model_path)
        except Exception as e:
            logger.warning(f"Could not persist HDBSCAN model to {self.model_path}: {e}")

        unique_labels = set(labels)
        noise_count = int(np.sum(labels == -1))
        clusters: List[ClusterItem] = []

        for cid in sorted(unique_labels):
            if cid == -1:
                continue  # Noise point

            indices = np.where(labels == cid)[0]
            cluster_pts = coords_array[indices]
            cluster_recs = [valid_records[i] for i in indices]

            # 1. Centroid calculation
            centroid_lat = float(np.mean(cluster_pts[:, 0]))
            centroid_lng = float(np.mean(cluster_pts[:, 1]))

            # 2. Bounding radius calculation (max haversine distance from centroid)
            max_dist = 0.0
            for pt in cluster_pts:
                dist = haversine_distance(centroid_lat, centroid_lng, pt[0], pt[1])
                if dist > max_dist:
                    max_dist = dist
            radius_meters = max(100.0, float(max_dist))

            # 3. Aggregate statistics
            acc_count = len(indices)
            total_fatalities = sum(int(r.get("fatalities", 0) or 0) for r in cluster_recs)
            total_injuries = sum(int(r.get("injuries", 0) or 0) for r in cluster_recs)

            # 4. Density (accidents per km²)
            radius_km = radius_meters / 1000.0
            area_km2 = max(0.01, math.pi * (radius_km ** 2))
            density = round(acc_count / area_km2, 2)

            # 5. Risk score formula (normalized 0.0 - 1.0)
            # Weighted impact: accident count (35%), fatalities (40%), injuries (15%), density (10%)
            raw_risk = (
                (min(acc_count, 50) / 50.0) * 0.35 +
                (min(total_fatalities, 20) / 20.0) * 0.40 +
                (min(total_injuries, 40) / 40.0) * 0.15 +
                (min(density, 100.0) / 100.0) * 0.10
            )
            risk_score = round(max(0.1, min(1.0, raw_risk)), 2)

            # 6. Classification into LOW, MEDIUM, HIGH, CRITICAL
            if risk_score >= settings.RISK_THRESHOLD_HIGH:
                risk_level = "CRITICAL"
                safety_rec = "High-severity accident cluster. Exercise extreme caution, enforce strict speed limits, and deploy speed calming."
            elif risk_score >= settings.RISK_THRESHOLD_MEDIUM:
                risk_level = "HIGH"
                safety_rec = "Elevated accident frequency. Watch for blind turns, crossing pedestrians, and slippery road conditions."
            elif risk_score >= settings.RISK_THRESHOLD_LOW:
                risk_level = "MEDIUM"
                safety_rec = "Moderate incident history. Maintain standard corridor speed and avoid aggressive lane changes."
            else:
                risk_level = "LOW"
                safety_rec = "Low incident zone. Standard cautious driving advised."

            cluster_item = ClusterItem(
                cluster_id=int(cid),
                accident_count=acc_count,
                latitude=round(centroid_lat, 6),
                longitude=round(centroid_lng, 6),
                radius_meters=round(radius_meters, 1),
                fatalities=total_fatalities,
                injuries=total_injuries,
                density=density,
                severity=risk_level,
                risk_score=risk_score,
                risk_level=risk_level,
                safety_recommendation=safety_rec,
            )
            clusters.append(cluster_item)

        logger.info(
            f"HDBSCAN clustering completed: {len(clusters)} clusters discovered, "
            f"{noise_count} noise points from {len(valid_records)} total records."
        )
        return clusters, len(clusters), noise_count

    def persist_clusters_to_db(
        self,
        db: Session,
        clusters: List[ClusterItem],
        replace_existing_ml: bool = True
    ) -> List[int]:
        """Save discovered clusters into the Hotspot table tagged as ML_DISCOVERED_HOTSPOT.
        Never modifies or removes KNOWN_BLACKSPOT records.
        """
        from app.models.hotspot import Hotspot
        from geoalchemy2.shape import from_shape
        from shapely.geometry import Point

        saved_ids = []
        try:
            if replace_existing_ml:
                # Remove prior ML-discovered hotspots only
                deleted = db.query(Hotspot).filter(
                    Hotspot.source == "ML_DISCOVERED_HOTSPOT"
                ).delete(synchronize_session=False)
                logger.info(f"Purged {deleted} obsolete ML_DISCOVERED_HOTSPOT records before refresh.")

            # Load all existing active hotspots to prevent duplicating physical locations
            existing_hotspots = db.query(Hotspot).filter(
                Hotspot.is_active == True
            ).all()

            count_before_cluster_add = len(existing_hotspots)
            accepted_new_spots: List[Hotspot] = []

            for c in clusters:
                # Deduplication check: Do not persist if cluster physical location is within 250m of any active hotspot
                is_duplicate = False
                for eh in existing_hotspots:
                    dist_to_existing = haversine_distance(c.latitude, c.longitude, eh.latitude, eh.longitude)
                    if dist_to_existing < 250.0:
                        logger.info(
                            f"[Hotspot Deduplication] Skipping ML cluster #{c.cluster_id + 1}: physical location already covered "
                            f"by existing blackspot '{eh.name}' (ID {eh.id}, {round(dist_to_existing, 1)}m away)."
                        )
                        c.db_hotspot_id = eh.id
                        is_duplicate = True
                        break

                # Also deduplicate against other clusters accepted in this same batch
                if not is_duplicate:
                    for accepted in accepted_new_spots:
                        dist_to_accepted = haversine_distance(c.latitude, c.longitude, accepted.latitude, accepted.longitude)
                        if dist_to_accepted < 250.0:
                            logger.info(
                                f"[Hotspot Deduplication] Skipping ML cluster #{c.cluster_id + 1}: physical location already covered "
                                f"by cluster '{accepted.name}' ({round(dist_to_accepted, 1)}m away)."
                            )
                            is_duplicate = True
                            break

                if is_duplicate:
                    continue

                point_geom = None
                try:
                    point_geom = from_shape(Point(c.longitude, c.latitude), srid=4326)
                except Exception:
                    pass

                new_spot = Hotspot(
                    name=f"ML Hotspot #{c.cluster_id + 1} ({c.risk_level})",
                    latitude=c.latitude,
                    longitude=c.longitude,
                    geom=point_geom,
                    risk_level=c.risk_level,
                    risk_score=c.risk_score,
                    density=c.density,
                    accident_count=c.accident_count,
                    fatalities=c.fatalities,
                    radius_meters=c.radius_meters,
                    safety_recommendation=c.safety_recommendation,
                    risk_factors=["HDBSCAN Density Cluster", f"{c.accident_count} Incident Concentration"],
                    description=f"AI-detected cluster from real incident spatial coordinates. Radius {c.radius_meters}m.",
                    algorithm="HDBSCAN",
                    source="ML_DISCOVERED_HOTSPOT",
                    is_active=True,
                    last_updated=datetime.now(timezone.utc)
                )
                db.add(new_spot)
                db.flush()
                c.db_hotspot_id = new_spot.id
                saved_ids.append(new_spot.id)
                accepted_new_spots.append(new_spot)

            db.commit()
            total_after_clusters = db.query(Hotspot).filter(Hotspot.is_active == True).count()
            logger.info(
                f"[Hotspot Deduplication] ML cluster persistence completed. "
                f"Candidate clusters: {len(clusters)}, Persisted new: {len(saved_ids)}, "
                f"Hotspots before: {count_before_cluster_add}, Hotspots after: {total_after_clusters}"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to persist ML clusters to DB: {e}")

        return saved_ids
