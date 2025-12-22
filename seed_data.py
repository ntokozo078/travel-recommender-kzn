from app import create_app, db
from app.models import Place

app = create_app()

def seed_database():
    with app.app_context():
        print("🗑️  Cleaning old data...")
        db.drop_all()
        db.create_all()

        print("🌍 Seeding Database with Beautiful Unsplash Images...")

        places = [
            # ==============================
            # 🛍️ SHOPPING & MALLS
            # ==============================
            Place(
                name="Gateway Theatre of Shopping", 
                category="Shopping", 
                description="The largest mall in the southern hemisphere. High-end fashion.", 
                address="Umhlanga Ridge", 
                opening_hours="09:00 - 19:00",
                # Unsplash: Modern Mall Architecture
                image_url="https://images.unsplash.com/photo-1519567241046-7f570eee3d9f?w=600&h=400&fit=crop",
                latitude=-29.7252, longitude=31.0658, is_indoor=True, has_generator=True, safety_score=5.0
            ),
            Place(
                name="The Pavilion Shopping Centre", 
                category="Shopping", 
                description="Iconic Westville mall with distinct domes and cinema.", 
                address="Jack Martens Dr, Westville", 
                opening_hours="09:00 - 19:00",
                # Unsplash: Busy Shopping Centre
                image_url="https://images.unsplash.com/photo-1567401893414-76b7b1e5a7a5?w=600&h=400&fit=crop",
                latitude=-29.8505, longitude=30.9317, is_indoor=True, has_generator=True, safety_score=4.8
            ),
            Place(
                name="Galleria Mall", 
                category="Shopping", 
                description="The South Coast's premier mall with ice skating and bowling.", 
                address="Amanzimtoti", 
                opening_hours="09:00 - 19:00",
                image_url="https://images.unsplash.com/photo-1534452203293-494d7ddbf7e0?w=600&h=400&fit=crop",
                latitude=-30.0436, longitude=30.8938, is_indoor=True, has_generator=True, safety_score=4.7
            ),
             Place(
                name="Victoria Street Market", 
                category="Shopping", 
                description="Historic market for Indian spices, African curios, and seafood.", 
                address="151 Victoria St, Durban", 
                opening_hours="08:00 - 17:00",
                # Unsplash: Spices / Market
                image_url="https://images.unsplash.com/photo-1533900298318-6b8da08a523e?w=600&h=400&fit=crop",
                latitude=-29.8569, longitude=31.0232, is_indoor=True, has_generator=False, safety_score=3.5
            ),

            # ==============================
            # 🥘 FAMOUS FOOD
            # ==============================
            Place(
                name="Britannia Hotel", 
                category="Food", 
                description="Legendary spot famous for the best Bunny Chows in Durban.", 
                address="1299 Umgeni Rd, Durban", 
                opening_hours="08:00 - 20:00",
                # Unsplash: Curry/Indian Food
                image_url="https://images.unsplash.com/photo-1604152135912-04a022e23696?w=600&h=400&fit=crop",
                latitude=-29.8240, longitude=31.0180, is_indoor=True, has_generator=True, safety_score=4.0
            ),
            Place(
                name="The Waffle House", 
                category="Food", 
                description="Famous landmark in Ramsgate serving sweet and savoury waffles.", 
                address="Ramsgate, South Coast", 
                opening_hours="08:00 - 17:00",
                # Unsplash: Waffles
                image_url="https://images.unsplash.com/photo-1562376552-0d160a2f238d?w=600&h=400&fit=crop",
                latitude=-30.8870, longitude=30.3470, is_indoor=True, has_generator=True, safety_score=4.8
            ),
            Place(
                name="Max's Lifestyle Village", 
                category="Food", 
                description="World-renowned authentic Shisa Nyama experience in Umlazi.", 
                address="Umlazi V Section", 
                opening_hours="10:00 - 22:00",
                # Unsplash: BBQ / Grill
                image_url="https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=600&h=400&fit=crop",
                latitude=-29.9658, longitude=30.8789, is_indoor=False, has_generator=True, safety_score=4.2
            ),
            Place(
                name="Florida Road", 
                category="Food", 
                description="The heart of Durban's nightlife, restaurants and bars.", 
                address="Morningside, Durban", 
                opening_hours="11:00 - 02:00",
                # Unsplash: Nightlife Street
                image_url="https://images.unsplash.com/photo-1514362545857-3bc16549766b?w=600&h=400&fit=crop",
                latitude=-29.8415, longitude=31.0220, is_indoor=False, has_generator=True, safety_score=4.0
            ),
             Place(
                name="Moyo uShaka Pier", 
                category="Food", 
                description="Cocktails and African cuisine right at the end of the pier over the ocean.", 
                address="uShaka Marine World", 
                opening_hours="11:00 - 23:00",
                # Unsplash: Cocktail by the sea
                image_url="https://images.unsplash.com/photo-1514362545857-3bc16549766b?w=600&h=400&fit=crop",
                latitude=-29.8680, longitude=31.0460, is_indoor=False, has_generator=True, safety_score=4.8
            ),

            # ==============================
            # 🏖️ BEACHES
            # ==============================
            Place(
                name="North Beach", 
                category="Beach", 
                description="The heart of the Golden Mile. Great for surfing and walking.", 
                address="O R Tambo Parade, Durban", 
                opening_hours="24 Hours",
                # Unsplash: Sunny Beach
                image_url="https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=600&h=400&fit=crop",
                latitude=-29.8540, longitude=31.0360, is_indoor=False, has_generator=False, safety_score=4.5
            ),
            Place(
                name="South Beach", 
                category="Beach", 
                description="Family-friendly beach with calm waters near uShaka.", 
                address="South Beach, Durban", 
                opening_hours="24 Hours",
                # Unsplash: Calm Beach
                image_url="https://images.unsplash.com/photo-1519046904884-53103b34b206?w=600&h=400&fit=crop",
                latitude=-29.8620, longitude=31.0420, is_indoor=False, has_generator=False, safety_score=4.4
            ),
            Place(
                name="Umhlanga Main Beach", 
                category="Beach", 
                description="Upscale beach with the Whalebone Pier and Lighthouse.", 
                address="Umhlanga Rocks", 
                opening_hours="24 Hours",
                # Unsplash: Lighthouse vibe
                image_url="https://images.unsplash.com/photo-1506953823976-52e1fdc0149b?w=600&h=400&fit=crop",
                latitude=-29.7270, longitude=31.0870, is_indoor=False, has_generator=False, safety_score=5.0
            ),
            Place(
                name="Richards Bay Alkantstrand", 
                category="Beach", 
                description="Blue Flag beach with warm water, great for dolphin watching.", 
                address="Richards Bay", 
                opening_hours="06:00 - 18:00",
                image_url="https://images.unsplash.com/photo-1520483601776-504df6d50feb?w=600&h=400&fit=crop",
                latitude=-28.7966, longitude=32.1030, is_indoor=False, has_generator=False, safety_score=4.3
            ),
             Place(
                name="Margate Beach", 
                category="Beach", 
                description="The holiday capital of the South Coast.", 
                address="Margate", 
                opening_hours="24 Hours",
                image_url="https://images.unsplash.com/photo-1509233725247-49e657c54213?w=600&h=400&fit=crop",
                latitude=-30.8640, longitude=30.3690, is_indoor=False, has_generator=False, safety_score=4.2
            ),
            Place(
                name="Sodwana Bay", 
                category="Beach", 
                description="World-famous diving and fishing destination with coral reefs.", 
                address="Sodwana Bay National Park", 
                opening_hours="24 Hours",
                # Unsplash: Diving/Coral vibe
                image_url="https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&h=400&fit=crop",
                latitude=-27.5414, longitude=32.6738, is_indoor=False, has_generator=False, safety_score=4.4
            ),

            # ==============================
            # 🐘 NATURE & WILDLIFE
            # ==============================
            Place(
                name="Tembe Elephant Park", 
                category="Nature", 
                description="Home to Africa's largest tuskers. Remote Big 5 reserve.", 
                address="Maputaland, KZN border", 
                opening_hours="06:00 - 18:00",
                # Unsplash: Elephant
                image_url="https://images.unsplash.com/photo-1557050543-4d5f4e64185f?w=600&h=400&fit=crop",
                latitude=-27.0456, longitude=32.4194, is_indoor=False, has_generator=False, safety_score=4.5
            ),
            Place(
                name="iSimangaliso Wetland Park", 
                category="Nature", 
                description="World Heritage Site. Hippos, crocs, and pristine nature.", 
                address="St Lucia", 
                opening_hours="06:00 - 18:00",
                # Unsplash: Wetlands/Nature
                image_url="https://images.unsplash.com/photo-1581850518616-6029633903a3?w=600&h=400&fit=crop",
                latitude=-28.3780, longitude=32.4109, is_indoor=False, has_generator=False, safety_score=4.6
            ),
            Place(
                name="Hluhluwe–iMfolozi Park", 
                category="Nature", 
                description="The oldest nature reserve in Africa. Best place to see Rhinos.", 
                address="Hluhluwe, KZN", 
                opening_hours="06:00 - 18:00",
                # Unsplash: Rhino
                image_url="https://images.unsplash.com/photo-1535338454770-8be927b5a00b?w=600&h=400&fit=crop",
                latitude=-28.2195, longitude=31.9525, is_indoor=False, has_generator=False, safety_score=4.7
            ),
            Place(
                name="Durban Botanic Gardens", 
                category="Nature", 
                description="Africa's oldest surviving botanic garden.", 
                address="Berea, Durban", 
                opening_hours="07:30 - 17:45",
                # Unsplash: Botanical Garden
                image_url="https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?w=600&h=400&fit=crop",
                latitude=-29.8475, longitude=31.0097, is_indoor=False, has_generator=False, safety_score=4.5
            ),

            # ==============================
            # ⛰️ ADVENTURE & INLAND
            # ==============================
            Place(
                name="Drakensberg Amphitheatre", 
                category="Nature", 
                description="Spectacular cliffs and Tugela Falls.", 
                address="Royal Natal National Park", 
                opening_hours="24 Hours",
                # Unsplash: Mountains
                image_url="https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=600&h=400&fit=crop",
                latitude=-28.9510, longitude=28.8940, is_indoor=False, has_generator=False, safety_score=4.7
            ),
            Place(
                name="Sani Pass", 
                category="Adventure", 
                description="4x4 route into Lesotho. Highest pub in Africa.", 
                address="Underberg", 
                opening_hours="06:00 - 18:00",
                # Unsplash: Mountain Road
                image_url="https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=600&h=400&fit=crop",
                latitude=-29.5840, longitude=29.2860, is_indoor=False, has_generator=False, safety_score=4.1
            ),
            Place(
                name="Moses Mabhida Stadium", 
                category="Adventure", 
                description="Take the SkyCar to the top or try the Big Rush Swing.", 
                address="Stamford Hill, Durban", 
                opening_hours="08:00 - 16:30",
                # Unsplash: Stadium
                image_url="https://images.unsplash.com/photo-1522770179533-24471fcdba45?w=600&h=400&fit=crop",
                latitude=-29.8290, longitude=31.0303, is_indoor=False, has_generator=True, safety_score=5.0
            ),
            Place(
                name="Oribi Gorge", 
                category="Adventure", 
                description="Scenic canyons, hiking, and the wild swing.", 
                address="Port Shepstone", 
                opening_hours="08:00 - 17:00",
                # Unsplash: Canyon/Gorge
                image_url="https://images.unsplash.com/photo-1504280506541-176329e19293?w=600&h=400&fit=crop",
                latitude=-30.6930, longitude=30.2640, is_indoor=False, has_generator=False, safety_score=4.5
            ),
            Place(
                name="Aliwal Shoal", 
                category="Adventure", 
                description="Shark diving and snorkeling.", 
                address="Umkomaas", 
                opening_hours="07:00 - 16:00",
                # Unsplash: Underwater/Shark
                image_url="https://images.unsplash.com/photo-1560275619-4662e36fa65c?w=600&h=400&fit=crop",
                latitude=-30.2070, longitude=30.7960, is_indoor=False, has_generator=False, safety_score=4.1
            ),

            # ==============================
            # 🏛️ CULTURE & HISTORY
            # ==============================
            Place(
                name="uShaka Marine World", 
                category="Entertainment", 
                description="World-class aquarium, water park, and penguin encounters.", 
                address="1 King Shaka Ave, Point", 
                opening_hours="09:00 - 17:00",
                # Unsplash: Aquarium
                image_url="https://images.unsplash.com/photo-1522069169874-c58ec4b76be5?w=600&h=400&fit=crop",
                latitude=-29.8677, longitude=31.0456, is_indoor=False, has_generator=True, safety_score=4.9
            ),
            Place(
                name="Nelson Mandela Capture Site", 
                category="Culture", 
                description="Historic sculpture marking Mandela's arrest.", 
                address="Howick", 
                opening_hours="09:00 - 17:00",
                # Unsplash: Sculpture/Museum
                image_url="https://images.unsplash.com/photo-1565063083321-729215091763?w=600&h=400&fit=crop",
                latitude=-29.4680, longitude=30.1710, is_indoor=False, has_generator=True, safety_score=4.9
            ),
            Place(
                name="Midlands Meander", 
                category="Food", 
                description="Famous route for craft beer, cheese, chocolate, and art.", 
                address="Midlands", 
                opening_hours="09:00 - 16:00",
                # Unsplash: Countryside/Wine
                image_url="https://images.unsplash.com/photo-1506377247377-2a5b3b417ebb?w=600&h=400&fit=crop",
                latitude=-29.4080, longitude=30.1290, is_indoor=False, has_generator=True, safety_score=5.0
            ),
            Place(
                name="Shakaland Cultural Village", 
                category="Culture", 
                description="Experience traditional Zulu culture, dancing, and food.", 
                address="Eshowe", 
                opening_hours="09:00 - 16:00",
                # Unsplash: Traditional Hut/Culture
                image_url="https://images.unsplash.com/photo-1496568816309-51d7c20e3b21?w=600&h=400&fit=crop",
                latitude=-28.8750, longitude=31.4640, is_indoor=False, has_generator=True, safety_score=4.5
            ),
             Place(
                name="Battlefields Route (Isandlwana)", 
                category="Culture", 
                description="Site of the historic Anglo-Zulu war battle.", 
                address="Isandlwana", 
                opening_hours="08:00 - 16:00",
                # Unsplash: Hills/Battlefield
                image_url="https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=600&h=400&fit=crop",
                latitude=-28.3580, longitude=30.6510, is_indoor=False, has_generator=False, safety_score=4.3
            ),
            Place(
                name="Howick Falls", 
                category="Nature", 
                description="Massive waterfall in the town center.", 
                address="Howick", 
                opening_hours="24 Hours",
                # Unsplash: Waterfall
                image_url="https://images.unsplash.com/photo-1433086966358-54859d0ed716?w=600&h=400&fit=crop",
                latitude=-29.4830, longitude=30.2330, is_indoor=False, has_generator=False, safety_score=4.2
            ),
            Place(
                name="KwaMuhle Museum", 
                category="Culture", 
                description="Museum detailing Durban's history.", 
                address="130 Bram Fischer Rd", 
                opening_hours="08:30 - 16:00",
                # Unsplash: Museum Building
                image_url="https://images.unsplash.com/photo-1518998053901-5348d3969105?w=600&h=400&fit=crop",
                latitude=-29.8517, longitude=31.0263, is_indoor=True, has_generator=False, safety_score=4.0
            )
        ]

        # Defaults
        for p in places:
            if not p.price_tier: p.price_tier = "$$"

        db.session.add_all(places)
        db.session.commit()
        print(f"✅ SUCCESS! Database seeded with High-Quality Unsplash Images.")

if __name__ == '__main__':
    seed_database()