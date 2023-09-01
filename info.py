import pymongo
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

async def add_connection(group_id: int, user_id: str) -> bool:
    try:
        async with AsyncIOMotorClient(DATABASE_URI) as myclient:
            mydb = myclient[DATABASE_NAME]
            mycol = mydb['CONNECTION']
            
            query = await mycol.find_one(
                { "_id": user_id },
                { "_id": 0, "active_group": 0 }
            )
            if query is not None:
                group_ids = [x["group_id"] for x in query["group_details"]]
                if group_id in group_ids:
                    return False
        
            group_details = {
                "group_id" : group_id
            }
        
            data = {
                '_id': user_id,
                'group_details' : [group_details],
                'active_group' : group_id,
            }
        
            if await mycol.count_documents( {"_id": user_id} ) == 0:
                await mycol.insert_one(data)
            else:
                await mycol.update_one(
                    {'_id': user_id},
                    {
                        "$push": {"group_details": group_details},
                        "$set": {"active_group" : group_id}
                    }
                )
            return True
    except pymongo.errors.ConnectionError as e:
        logger.exception('Failed to connect to the database.', exc_info=True)
        return False


async def active_connection(user_id: str) -> typing.Optional[int]:
    try:
        async with AsyncIOMotorClient(DATABASE_URI) as myclient:
            mydb = myclient[DATABASE_NAME]
            mycol = mydb['CONNECTION']
        
            query = await mycol.find_one(
                { "_id": user_id },
                { "_id": 0, "group_details": 0 }
            )
            if not query:
                return None
        
            group_id = query['active_group']
            return int(group_id) if group_id != None else None
    except pymongo.errors.ConnectionError as e:
        logger.exception('Failed to connect to the database.', exc_info=True)
        return None


async def all_connections(user_id: str) -> typing.Optional[typing.List[int]]:
    try:
        async with AsyncIOMotorClient(DATABASE_URI) as myclient:
            mydb = myclient[DATABASE_NAME]
            mycol = mydb['CONNECTION']
        
            query = await mycol.find_one(
                { "_id": user_id },
                { "_id": 0, "active_group": 0 }
            )
            if query is not None:
                return [x["group_id"] for x in query["group_details"]]
    else:
