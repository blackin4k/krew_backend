DO $$
DECLARE
    target_song_ids INTEGER[];
BEGIN
    -- 1. Identify IDs of songs to be deleted
    SELECT ARRAY(
        SELECT id FROM song WHERE audio_file IN (
            '112 - The Weeknd - Acquainted.mp3',
            '137 - The Weeknd - Acquainted.mp3',
            '082 - The Weeknd - After Hours.mp3',
            '138 - The Weeknd - After Hours.mp3',
            '029 - Radiohead - All I Need.mp3',
            '070 - The Weeknd - Alone Again.mp3',
            '063 - The Weeknd - A Lonely Night.mp3',
            '064 - The Weeknd - Attention.mp3',
            '07 - Himesh Reshammiya - Bewajah.mp3',
            '95c8bd6c-a436-4038-997c-e87edd5a1df0_07 - Himesh Reshammiya - Bewajah.mp3',
            '078 - The Weeknd - Blinding Lights.mp3',
            '106 - The Weeknd - Blinding Lights.mp3',
            '124 - The Weeknd - Blinding Lights.mp3',
            '133 - The Weeknd - Call Out My Name.mp3',
            '127 - The Weeknd - Can''t Feel My Face.mp3',
            '167 - The Weeknd - Coming Down.mp3',
            '036 - Radiohead - Creep.mp3',
            '085 - The Weeknd - Cry For Me.mp3',
            '068 - The Weeknd - Die For You.mp3',
            '121 - The Weeknd - Die For You.mp3',
            '101 - The Weeknd - Drive.mp3',
            '307 - Olivia Rodrigo - drivers license.mp3',
            '115 - The Weeknd - Earned It (Fifty Shades Of Grey).mp3',
            '136 - The Weeknd - Earned It (Fifty Shades Of Grey).mp3',
            '075 - The Weeknd - Escape From LA.mp3',
            '004 - Radiohead - Exit Music (For A Film).mp3',
            '077 - The Weeknd - Faith.mp3',
            '054 - The Weeknd - False Alarm.mp3',
            '100 - The Weeknd - Give Me Mercy.mp3',
            '094 - The Weeknd - Given Up On Me.mp3',
            '14 - Lata Mangeshkar - Ham Tere Pyar Mein.mp3',
            '072 - The Weeknd - Hardest To Love.mp3',
            '076 - The Weeknd - Heartless.mp3',
            '130 - The Weeknd - Heartless.mp3',
            '156 - The Weeknd - High For This.mp3',
            '161 - The Weeknd - High For This.mp3',
            '142 - The Weeknd - House Of Balloons ⧸ Glass Table Girls.mp3',
            '163 - The Weeknd - House Of Balloons ⧸ Glass Table Girls.mp3',
            '105 - The Weeknd - Hurry Up Tomorrow.mp3',
            '095 - The Weeknd - I Can''t Wait To Get There.mp3',
            '128 - The Weeknd, Daft Punk - I Feel It Coming.mp3',
            '20 - Asha Bhosle - In Ankhon Ki Masti.mp3',
            '150 - The Weeknd - In The Night.mp3',
            '079 - The Weeknd - In Your Eyes.mp3',
            '125 - The Weeknd - In Your Eyes.mp3',
            '144 - The Weeknd - Is There Someone Else？.mp3',
            '005 - Radiohead - Let Down.mp3',
            '168 - The Weeknd - Loft Music.mp3',
            '062 - The Weeknd - Love To Lay.mp3',
            '658 - Tame Impala - Nangs.mp3',
            '097 - The Weeknd - Niagara Falls.mp3',
            '066 - The Weeknd - Nothing Without You.mp3',
            '110 - The Weeknd - Often.mp3',
            '134 - The Weeknd - Often.mp3',
            '091 - The Weeknd - Opening Night.mp3',
            '065 - The Weeknd - Ordinary Life.mp3',
            '053 - The Weeknd - Party Monster.mp3',
            '145 - The Weeknd - Party Monster.mp3',
            '103 - The Weeknd - Red Terror.mp3',
            '055 - The Weeknd - Reminder.mp3',
            '149 - The Weeknd - Reminder.mp3',
            '081 - The Weeknd - Repeat After Me (Interlude).mp3',
            '056 - The Weeknd - Rockin’.mp3',
            '157 - The Weeknd, Anitta - São Paulo.mp3',
            '158 - The Weeknd, Anitta - São Paulo.mp3',
            '159 - The Weeknd, Anitta - São Paulo.mp3',
            '160 - The Weeknd, Anitta - São Paulo.mp3',
            '080 - The Weeknd - Save Your Tears.mp3',
            '123 - The Weeknd - Save Your Tears.mp3',
            '073 - The Weeknd - Scared To Live.mp3',
            '057 - The Weeknd - Secrets.mp3',
            '061 - The Weeknd - Six Feet Under.mp3',
            '074 - The Weeknd - Snowchild.mp3',
            '122 - The Weeknd, Daft Punk - Starboy.mp3',
            '146 - The Weeknd, Lana Del Rey - Stargirl Interlude.mp3',
            '098 - The Weeknd - Take Me Back To LA.mp3',
            '147 - The Weeknd - Tell Your Friends.mp3',
            '111 - The Weeknd - The Hills.mp3',
            '131 - The Weeknd - The Hills.mp3',
            '169 - The Weeknd - The Knowing.mp3',
            '132 - The Weeknd - The Morning.mp3',
            '164 - The Weeknd - The Morning.mp3',
            '166 - The Weeknd - The Party & The After Party.mp3',
            '071 - The Weeknd - Too Late.mp3',
            '306 - Olivia Rodrigo - traitor.mp3',
            '058 - The Weeknd - True Colors.mp3',
            '083 - The Weeknd - Until I Bleed Out.mp3',
            '088 - The Weeknd - Until We''re Skin & Bones.mp3',
            '162 - The Weeknd - What You Need.mp3',
            '126 - The Weeknd - Wicked Games.mp3',
            '165 - The Weeknd - Wicked Games.mp3',
            '104 - The Weeknd - Without a Warning.mp3'
        )
    ) INTO target_song_ids;

    -- 2. Delete/Update references in dependent tables
    IF array_length(target_song_ids, 1) > 0 THEN
        DELETE FROM play_logs WHERE song_id = ANY(target_song_ids);
        DELETE FROM playlist_song WHERE song_id = ANY(target_song_ids);
        DELETE FROM "like" WHERE song_id = ANY(target_song_ids);
        DELETE FROM queue_history WHERE song_id = ANY(target_song_ids);
        UPDATE playback_state SET current_song_id = NULL WHERE current_song_id = ANY(target_song_ids);
        UPDATE external_playlist_track SET song_id = NULL WHERE song_id = ANY(target_song_ids);

        -- 3. Delete from main song table
        DELETE FROM song WHERE id = ANY(target_song_ids);
    END IF;
END $$;